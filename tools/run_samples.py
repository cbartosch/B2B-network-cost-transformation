"""Run the outside-in workflow end to end for each company in
samples/companies.json, and store what it produced under samples/outside_in/.

The spec and the output are in different directories on purpose - see
SPEC_RELATIVE.

LIVE throughout. Entity resolution and all seventeen agent-routed domains
make real provider calls with hosted web search, so one company is tens of
minutes and the set is hours. Nothing here is cached between companies: each
is its own case, and the schema makes that structural rather than a promise -
outside_in, analysis and agent_runtime are keyed by case_id and reference is
not, so twenty cases cannot contaminate each other.

Resumable. A company whose directory already holds a complete estimate is
skipped unless --force, because a provider spend that has already happened
should not happen twice for a re-run of the loop.

Usage, from the bundle root with the stack up:

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \\
        python tools/run_samples.py --out /src/samples/outside_in'

    --only tesco,basf     run a subset
    --force               re-run companies that already have results
    --domains 1,2,6,7,8   research only these domains (a cheaper pilot)
"""
import argparse
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D

from sqlalchemy import select

from app import _version, db
from app.domain import dispositions, footprint, research

API = "http://127.0.0.1:8000"

# The seventeen domains a research agent is routed to. The other seven are
# analyst or policy domains with no agent behind them, so asking for them
# would be a call that cannot answer.
AGENT_DOMAINS = sorted(n for n, a in research.DOMAIN_AGENT_MAP.items() if a)

# Seconds to wait before re-attempting a domain that failed on infrastructure.
# Long enough for a DNS blip or a provider 5xx to clear, short enough that two
# retries do not dominate a run that is already minutes per domain.
BLOCKED_RETRY_WAIT = 60

# The other seven: 3, 4, 5, 11, 17, 23, 24. No agent is routed to them, so
# nothing researches them and V0 refuses to publish while any of the 24 has
# no disposition - correctly, because an undisposed domain is one nobody has
# said anything about. They are disposed BENCHMARK_PRIOR: this estimate rests
# on the seeded priors for archetypes, bandwidth, remote users, operating
# model, resilience, the northstar set and the confidence metadata, and
# saying so is what keeps the confidence model honest about them.
ANALYST_DOMAINS = sorted(n for n, a in research.DOMAIN_AGENT_MAP.items()
                         if not a)

# One seed for the whole set, so a re-run reproduces every estate and a
# difference between two companies is the company rather than the draw.
SEED = 20260101
ENSEMBLE = 25
ANALYST = "sample-run"

# The domains whose findings the summary leads on. The rest are kept in full
# in research.json; these are the ones a reader asks about first.
HIGHLIGHT_DOMAINS = {
    1: "profile", 2: "locations", 6: "data_centres", 7: "architecture",
    8: "vendors", 12: "contracts", 14: "transformation", 18: "serviceability",
}


def call(method, path, body=None, timeout=2400):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:                                    # noqa: BLE001
            return e.code, None
    except Exception as e:                                   # noqa: BLE001
        return 0, {"transport_error": f"{type(e).__name__}: {e}"}


def log(slug, msg):
    print(f"  [{slug}] {msg}", flush=True)


# slug -> case_id, written the moment a case is created.
#
# Research skips a domain that already carries a disposition - that is what
# _existing_domain_nos is for, and the endpoint's own comment says "a walk
# that stops halfway resumes rather than restarts". But only within one case,
# and this driver used to create a new one on every attempt, so a company
# that failed late threw away every domain it had paid for. Seven did,
# together holding 118 researched domains.
#
# Kept as a file rather than inferred from the database: two companies can
# share a legal name prefix, and guessing which case belongs to which slug is
# exactly the kind of inference that should not sit between a re-run and real
# money.
def ledger_path(outdir):
    return outdir / "_cases.json"


def ledger_read(outdir):
    f = ledger_path(outdir)
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


def ledger_write(outdir, slug, case_id):
    f = ledger_path(outdir)
    data = ledger_read(outdir)
    data[slug] = case_id
    f.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def case_is_usable(case_id):
    """Exists, and carries the confirmation pre-flight insists on."""
    with db.SessionLocal() as s:
        row = s.execute(select(
            db.case.c.case_id, db.case.c.entity_confirmed_at).where(
                db.case.c.case_id == case_id)).first()
    return bool(row and row.entity_confirmed_at)


def researched_domains(case_id):
    """Domains already carrying an agent's verdict, so already paid for."""
    with db.SessionLocal() as s:
        rows = s.execute(select(db.domain_disposition.c.domain_no).where(
            db.domain_disposition.c.case_id == case_id,
            db.domain_disposition.c.agent_run_id.isnot(None))).all()
    return {r.domain_no for r in rows}


# ----------------------------------------------------------------- the steps
def intake(spec):
    st, case = call("POST", "/v1/outside-in/cases", {
        "created_by": ANALYST,
        "subject_entity_legal_name": spec["legal_name"],
        # Mandatory intake requires an identifier, and a successful
        # resolution overwrites this with the real one. Deliberately not a
        # plausible-looking LEI: inventing an identifier that reads as real
        # is worse than carrying one that cannot be mistaken for anything.
        # Three companies failed pre-flight on "Mandatory intake, Entity
        # resolution" because this field was never sent and resolution did
        # not fill it in.
        "entity_identifier": f"SAMPLE-NOT-A-REAL-IDENTIFIER-{spec['slug']}",
        "entity_aliases": spec.get("aliases") or [],
        "country_of_domicile": spec["domicile"],
        "group_perimeter": "GROUP_CONSOLIDATED",
        "in_scope_countries": spec["countries"],
        "in_scope_cost_layers": ["L0", "L1", "L2", "L4", "OPS"],
        "in_scope_service_families": ["WAN", "INTERNET"],
        "base_currency": spec["currency"],
        "price_year": 2026,
        "fx_convention": "SPOT",
        "analysis_horizon_years": 3,
        "discount_rate_set_id": "default",
        "engagement_purpose": "COST_TRANSFORMATION",
        # No contact: this is an outside-in estimate about a public company,
        # built only from public evidence. Saying so here is what keeps
        # CLIENT_CONFIRMED off every disposition downstream.
        "client_contact_status": "NO_CONTACT",
        "baseline_reference_period": "FY2025"})
    if st != 200:
        raise RuntimeError(f"intake {st}: {case}")
    return case["case_id"]


def resolve_and_confirm(case_id, spec):
    """Real resolution, not a direct write.

    The candidate carries the resolver's own description of the sector,
    which confirmation records as industry_as_resolved for the cross-check
    in set_industry_if_absent. It does not carry the taxonomy code that keys
    archetype_bandwidth and archetype_resilience: that comes from the spec.
    """
    def _fallback(why):
        """Confirm directly, the way the flow test does when no provider is
        configured - the same state a real resolution would leave behind.

        Without it a failed resolution left the case unconfirmed, pre-flight
        raised a BLOCK on "Entity resolution", acknowledge does not clear a
        BLOCK, and the simulation refused with 409 - after the research had
        already been paid for. Three companies died that way. The fallback is
        recorded, so a case confirmed this way is never mistaken for one the
        resolver actually identified.
        """
        from sqlalchemy import update
        with db.SessionLocal() as s:
            s.execute(update(db.case).where(db.case.c.case_id == case_id)
                      .values(resolved_entity_id=f"SAMPLE-{spec['slug']}",
                              entity_confirmed_by=ANALYST,
                              entity_confirmed_at=datetime.now(timezone.utc)))
            s.commit()
        return {"resolved": False, "confirmed_by_fallback": True,
                "detail": why}

    st, out = call("POST", f"/v1/outside-in/cases/{case_id}/entities:resolve",
                   {"name_hint": spec["legal_name"], "mode": "LIVE"},
                   timeout=900)
    if st != 200:
        return _fallback(f"resolve {st}: {out}")

    cands = (out or {}).get("candidates") or []
    if not cands:
        return _fallback("no candidates proposed")

    pick = cands[0]
    st, conf = call("POST", f"/v1/outside-in/cases/{case_id}:confirm-entity", {
        "candidate_id": pick["candidate_id"], "confirmed_by": ANALYST,
        "group_perimeter": "GROUP_CONSOLIDATED"}, timeout=300)
    if st != 200:
        return _fallback(f"confirm {st}: {conf}")
    return {"resolved": True, "candidate": pick,
            "candidates_considered": len(cands)}


def set_industry_if_absent(case_id, spec):
    """The spec's industry code, unless the case already holds a known one.

    Recorded in the manifest either way. An industry the seed does not know
    silently falls back to DEFAULT and the estate stops differentiating, so
    this is not a cosmetic field.

    Nothing else writes the code. Resolution records what it called the
    sector as industry_as_resolved and leaves the code alone, so a known
    code on a case came from the spec - this function, on this run or an
    earlier one - or from whoever set it on the case. Labelling every known
    code ENTITY_RESOLUTION, as this did, credited research with a choice it
    never makes: true of none of the fifty, and Maersk and Michelin said
    SPEC_FALLBACK only on the run that wrote their codes.
    """
    from sqlalchemy import update
    from app.domain import bics
    with db.SessionLocal() as s:
        row = s.execute(select(db.case.c.industry).where(
            db.case.c.case_id == case_id)).scalar()
        resolved_text = s.execute(select(db.case.c.industry_as_resolved).where(
            db.case.c.case_id == case_id)).scalar()
        known = {r[0] for r in s.execute(
            select(db.archetype_bandwidth.c.industry)).all()}
        if row and row.upper() in known:
            # The spec's code, or one the case was given some other way -
            # kept either way. Which one is reported, and a disagreement is
            # said out loud by the caller: a corrected spec does not
            # overwrite a known code, and nothing used to say so.
            out = {"industry": row,
                   "origin": ("SPEC_FALLBACK"
                              if row.upper() == spec["industry"].upper()
                              else "CASE_RECORD")}
        else:
            s.execute(update(db.case).where(db.case.c.case_id == case_id)
                      .values(industry=spec["industry"]))
            s.commit()
            out = {"industry": spec["industry"], "origin": "SPEC_FALLBACK"}

    # The cross-check. The membership test above asks whether the code is A
    # code; this asks whether it is THIS ENTITY'S code, which is the question
    # that went unasked while UNFI ran as WAREHOUSING.
    #
    # Reported, never applied. Free text cannot settle a taxonomy, and a
    # check that silently re-labelled a case would be worse than the gap it
    # closes - the code drives bandwidth, resilience and the estate shape,
    # and being wrong in either direction is expensive.
    out["resolution_said"] = resolved_text
    out["agrees_with_resolution"] = bics.industry_text_agrees(
        out["industry"], resolved_text)
    return out


def preflight(case_id):
    st, report = call("POST", f"/v1/outside-in/cases/{case_id}/preflight:run",
                      {}, timeout=300)
    if st != 200:
        raise RuntimeError(f"preflight {st}: {report}")
    st, ack = call("POST",
                   f"/v1/outside-in/cases/{case_id}/preflight:acknowledge",
                   {"report_id": report["report_id"],
                    "acknowledged_by": ANALYST}, timeout=300)
    if st != 200:
        raise RuntimeError(f"acknowledge {st}: {ack}")
    return report


def fell_back_domains(case_id, agent_domains):
    """Domains disposed by the safety net rather than by an agent.

    A domain the fallback disposed carries BENCHMARK_PRIOR and no
    agent_run_id, and research then skips it forever - _existing_domain_nos
    counts any disposition, so the net that keeps a company publishable also
    locks the domain out of a later attempt. That is fine when the agent
    genuinely had nothing to say and wrong when the provider was unreachable,
    which is what happened here: DNS inside the container stopped resolving
    api.anthropic.com partway through the run, every call returned
    ProviderUnavailable, and seven companies had all seventeen domains
    disposed by the net.
    """
    with db.SessionLocal() as s:
        rows = s.execute(select(
            db.domain_disposition.c.domain_no,
            db.domain_disposition.c.agent_run_id,
            db.domain_disposition.c.reason).where(
                db.domain_disposition.c.case_id == case_id)).all()
    return sorted(r.domain_no for r in rows
                  if r.domain_no in set(agent_domains)
                  and not r.agent_run_id
                  and (r.reason or "").startswith("research returned no"))


def do_research(case_id, slug, domains, overwrite=False):
    """One domain per call.

    The endpoint's own note: a full seventeen-domain run is minutes of LIVE
    provider calls and source fetches, which no HTTP client will wait for.
    Walking them one at a time also means a domain that fails costs that
    domain rather than the run.
    """
    out = {}
    for n in domains:
        t0 = time.time()
        st, res = call("POST",
                       f"/v1/outside-in/cases/{case_id}/domain-research:run",
                       {"domain_nos": [n], "provider": "anthropic",
                        "overwrite": overwrite},
                       timeout=2400)
        took = round(time.time() - t0, 1)
        out[n] = {"status": st, "seconds": took, "result": res}
        name = dict(dispositions.DOMAINS).get(n, "?")
        if st == 200:
            got = (res or {}).get("results") or []
            # str(), because disposition comes back None when the agent run
            # produced no verdict, and `{None:<18}` raises TypeError. That
            # killed four companies outright - tesco, allianz, shell and
            # saint-gobain - each after an hour of paid research, on a
            # logging format string. A progress line must never be able to
            # end a run.
            one = (got[0] or {}) if got else {}
            # A domain the provider could not be reached for and a domain the
            # agent had nothing to say about both arrive with disposition
            # None, and this line printed "-" for both. Fraport spent twelve
            # domains on a DNS outage and the log called it research.
            #
            # research.py already separates them - failure_kind and retryable
            # exist precisely because "the distinction was always here and
            # only ever in English" - and this driver was never taught to read
            # them. An infrastructure failure now says so on its own line.
            if one.get("failed"):
                kind = one.get("failure_kind") or "FAILED"
                mark = "retryable" if one.get("retryable") else "permanent"
                log(slug, f"domain {n:>2} {name[:34]:<34} {kind:<18} {took}s "
                          f"({mark})")
                log(slug, f"         {(one.get('failure_detail') or '')[:120]}")
            else:
                disp = str(one.get("disposition") or "-") if got else "-"
                log(slug, f"domain {n:>2} {name[:34]:<34} {disp:<18} {took}s")
        else:
            log(slug, f"domain {n:>2} {name[:34]:<34} FAILED {st} ({took}s)")
    return out


def transport_blocked(raw):
    """Domains whose last attempt failed for a reason retrying could fix.

    PROVIDER_UNAVAILABLE, LIVENESS_PROOF_FAILED and SOURCES_UNREACHABLE are
    infrastructure, not findings. A domain that hit one of them was never
    asked the question, so it must not be recorded as having been asked and
    answered with nothing.
    """
    blocked = {}
    for n, got in (raw or {}).items():
        res = (got or {}).get("result") or {}
        for one in (res.get("results") or []):
            if one.get("failed") and one.get("retryable"):
                blocked[n] = one.get("failure_kind") or "FAILED"
    return blocked


def dispose_analyst_domains(case_id, slug, researching, keep=()):
    """The seven domains no agent covers.

    BEFORE research, and the ordering is load-bearing. PUT
    /domain-dispositions is a whole-case replacement: its own code deletes
    every domain absent from the payload -

        # Domains absent from the payload are removed, preserving the
        # previous whole-case-replacement semantics the interface relies on.
        for domain_no in set(existing) - incoming:

    - so sending these seven after research deletes the seventeen the agents
    disposed, with their evidence blobs and their agent_run_ids. That is the
    provenance for seventeen paid LIVE calls, and `provenance_dropped` in the
    response does not mention it: that list covers domains re-dispositioned
    in the payload, not domains dropped by omission. The first run of this
    script did exactly that and lost two researched domains silently.

    Research upserts on top of these afterwards, which is safe in that
    direction.
    """
    names = dict(dispositions.DOMAINS)
    # Everything this run will not research - the seven with no agent, plus
    # any agent domain left out of --domains. V0 refuses to publish while any
    # of the 24 is undisposed, and a domain nobody researched resting on the
    # seeded prior is exactly what BENCHMARK_PRIOR means. The manifest records
    # which domains were researched, so the two are never confused.
    # ... AND NOT A DOMAIN THAT ALREADY HOLDS A VERDICT.
    #
    # The paragraph above describes losing two researched domains to this
    # function. It happened again, larger: a --redo run asked for domain 19
    # alone, so `researching` was [19] and this disposed the other
    # twenty-three - including the sixteen that held paid agent verdicts -
    # on three companies at once. Forty-eight researched domains, with
    # their evidence blobs and agent_run_ids, replaced by BENCHMARK_PRIOR
    # before the new research even started. The log said "disposed 23
    # domain(s)" and nothing said what twenty-three meant.
    #
    # Disposing a researched domain as BENCHMARK_PRIOR is always wrong: it
    # asserts the estimate rests on a seeded prior for something an agent
    # actually answered. On a fresh case `keep` is empty and this is the
    # behaviour it always had.
    keep = set(keep)
    todo = [n for n, _ in dispositions.DOMAINS
            if n not in set(researching) and n not in keep]
    st, out = call("PUT",
                   f"/v1/outside-in/cases/{case_id}/domain-dispositions",
                   [{"domain_no": n, "domain_name": names[n],
                     "disposition": "BENCHMARK_PRIOR"}
                    for n in todo], timeout=300)
    if st != 200:
        raise RuntimeError(f"dispositions {st}: {out}")
    # Not logging publication_blockers from this response: the endpoint
    # computes them with dispositions.validate(records) over the *payload*,
    # so a seven-record PUT reports the other seventeen as missing whatever
    # the case actually holds. The estimate call is what tells us.
    log(slug, f"disposed {len(todo)} domain(s) BENCHMARK_PRIOR "
              f"ahead of research"
              + (f", keeping {len(keep)} already researched" if keep else ""))
    return out


def dispose_unanswered(case_id, slug, blocked=()):
    """Whatever research could not answer falls back to the seeded prior.

    `blocked` names domains that failed on infrastructure - the provider was
    unreachable, the call could not be proven to have run, egress refused the
    fetch. Those are NEVER disposed here. BENCHMARK_PRIOR with "research
    returned no verdict" asserts that research ran and established nothing,
    and a domain that never reached the provider has established nothing
    about anything. Writing it anyway is how a DNS outage became twelve of
    Fraport's seventeen domains and a published estimate that read as
    researched.

    Leaving them undisposed is deliberate and has a cost: V0 refuses to
    publish a case with an undisposed domain, so the company fails the run.
    That is the intended outcome. A company missing from the set is a visible
    gap; a company in the set resting on a silent outage is not.

    A research call can return 200 and no verdict - the agent ran, the
    quality gate refused every attempt, and _upsert_disposition is only
    reached when the result did not fail. The domain is then left with no
    disposition at all, and V0 refuses to publish because an undisposed
    domain is one nobody has said anything about. That is the right refusal
    and the wrong outcome here: tesco spent 1,309s on domain 20 and 1,318s
    on 21, got no verdict for either, and lost the whole estimate at the
    final step.

    BENCHMARK_PRIOR is the honest fallback - this domain rests on the seeded
    prior because nothing else could be established - and the manifest
    records which domains it covers, so one that fell back is never counted
    as one that was researched.

    Safe only because PUT /domain-dispositions no longer deletes the domains
    absent from its payload. Before that fix this call would have wiped every
    researched disposition on the case.
    """
    with db.SessionLocal() as s:
        have = {r.domain_no for r in s.execute(
            select(db.domain_disposition.c.domain_no).where(
                db.domain_disposition.c.case_id == case_id)).all()}
    names = dict(dispositions.DOMAINS)
    missing = [n for n, _ in dispositions.DOMAINS
               if n not in have and n not in set(blocked)]
    if blocked:
        detail = ", ".join(f"{n} {k}" for n, k in sorted(dict(blocked).items()))
        log(slug, f"NOT disposing {len(blocked)} domain(s) blocked on "
                  f"infrastructure: {detail}")
    if not missing:
        return {"fell_back": [], "blocked": dict(blocked or {})}
    st, out = call("PUT",
                   f"/v1/outside-in/cases/{case_id}/domain-dispositions",
                   [{"domain_no": n, "domain_name": names[n],
                     "disposition": "BENCHMARK_PRIOR",
                     "reason": "research returned no verdict"}
                    for n in missing], timeout=300)
    if st != 200:
        raise RuntimeError(f"fallback dispositions {st}: {out}")
    log(slug, f"{len(missing)} domain(s) research could not answer fell back "
              f"to BENCHMARK_PRIOR: {missing}")
    return {"fell_back": missing, "blocked": dict(blocked or {})}


def promote(case_id, slug):
    st, cands = call("GET",
                     f"/v1/outside-in/cases/{case_id}/research-findings",
                     timeout=300)
    if st != 200:
        return {"promoted": False, "detail": f"{st}: {cands}"}
    # footprint_candidates, and candidate_id - the bucket names and the id
    # field are promotion.candidates()' own, not guesses.
    #
    # PRICES WERE DROPPED HERE. This read footprint_candidates alone, and the
    # promote endpoint has always handled both - its own docstring says
    # "Move selected findings into the footprint AND THE PRICE PRIORS". So
    # research bought 82 country prices across the 41 companies, the
    # classifier routed all 82 to price_candidates, and the driver never
    # passed their ids. Ten prices reached the rate card in the whole set,
    # every one of them put there by hand.
    #
    # The cost of that is the headline: 86.1% of a EUR 500m baseline rests on
    # seeded priors, and the evidence to replace a large part of it was
    # already bought, already classified, and sitting in the candidate list.
    #
    # Safe to promote without a second thought because a promoted price is
    # NOT a used price: research writes reference.unit_cost_prior with
    # approved=False and the estimate reads only approved rows. Promoting
    # makes the number visible and attributable; a steward still decides
    # whether it prices anything.
    buckets = ("footprint_candidates", "price_candidates")
    by_bucket = {b: [c.get("candidate_id")
                     for c in (cands or {}).get(b) or []] for b in buckets}
    ids = [i for b in buckets for i in by_bucket[b] if i]
    if not ids:
        return {"promoted": False, "detail": "no candidates",
                "candidates": cands}
    st, res = call("POST",
                   f"/v1/outside-in/cases/{case_id}/research-findings:promote",
                   {"candidate_ids": ids, "promoted_by": ANALYST},
                   timeout=600)
    # Decisions a steward already made on these prices, which promotion now
    # leaves standing: kept where research found the decided figure again,
    # challenged where it found another - a figure a steward should see, and
    # the card does not take. Logged, because a re-run that silently reset
    # approvals is what this line used to hide.
    kept = (res or {}).get("decisions_kept") or [] if st == 200 else []
    challenged = ((res or {}).get("decisions_challenged") or []
                  if st == 200 else [])
    log(slug, f"promote {len(by_bucket['footprint_candidates'])} footprint "
              f"+ {len(by_bucket['price_candidates'])} price finding(s): {st}"
              + (f"; kept {len(kept)} price decision(s)" if kept else "")
              + (f"; {len(challenged)} challenged by another figure: "
                 + ", ".join(f"{d['id']} ({d['found']} against "
                             f"{d['decided']})" for d in challenged)
                 if challenged else ""))
    return {"promoted": st == 200, "ids": ids,
            "price_ids": by_bucket["price_candidates"], "result": res}


#: Where the committed spec lives, relative to the repository root and to the
#: image root. Both are checked because this script runs from either.
#:
#: Deliberately OUTSIDE samples/outside_in/, which is the published output.
#: It sat inside it, and publishing a run copies that whole directory back
#: over the repository - so the output overwrote the input. That is how the
#: commit which stopped the driver READING from its output directory also
#: replaced the committed spec with a stale one it had just been handed.
#: Separate directories make the collision unrepresentable rather than
#: merely discouraged.
SPEC_RELATIVE = pathlib.Path("samples") / "companies.json"

#: Filled in by main() once the spec is resolved, and written into every
#: manifest. Module-level because every company in a run reads the same
#: spec, and threading it through each call site would invite one that
#: does not.
SPEC_IDENTITY: dict = {"path": None, "digest": None}


def resolve_spec(explicit: str, outdir: pathlib.Path) -> pathlib.Path:
    """Where the company spec comes from, which is never the output directory.

    It used to be `outdir / "companies.json"`, and that is a loaded gun. The
    driver's output directory is pulled out of the container before a restart
    and pushed back in afterwards, so the INPUT travelled inside the OUTPUT:
    a spec committed to the repository reached a re-run only if somebody
    remembered to copy it in by hand.

    Nobody did. Six companies silently reverted to a scope three commits old
    - BASF 219 sites to 101, Siemens 495 to 195, Unilever 214 to 43 - because
    the restored copy predated CR-02b. The run completed, every company
    reported success, the validation gate passed, and the only visible signal
    was estates shrinking in industries the change under test did not touch.
    One more step and it would have been published.

    So the output directory is refused outright rather than demoted in a
    precedence order. A fallback that silently reads the wrong file is the
    defect; making it the last resort would only make it rarer.
    """
    outdir = outdir.resolve()
    if explicit:
        found = pathlib.Path(explicit).resolve()
        if not found.exists():
            raise SystemExit(f"--spec {found} does not exist")
    else:
        here = pathlib.Path(__file__).resolve()
        candidates = [here.parents[1] / SPEC_RELATIVE,        # a repo checkout
                      pathlib.Path("/app") / SPEC_RELATIVE]   # the image
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            raise SystemExit(
                "no company spec found at " +
                " or ".join(str(c) for c in candidates) +
                ". Pass --spec. It is NOT read from --out: a spec that "
                "travels with the output is restored from backups and goes "
                "stale without saying so.")
    if found == outdir / "companies.json" or outdir in found.parents:
        raise SystemExit(
            f"refusing to read the spec from inside --out ({found}). That "
            f"directory is restored from a backup before a re-run, so a spec "
            f"living in it is whatever the last restore happened to carry - "
            f"which once reverted six companies to a three-commit-old scope "
            f"without any error. Pass --spec with the committed file.")
    return found


def _scope_exclusions(spec) -> list:
    """Normalised `excluded` entries from a company spec.

    Each is {country, archetype, reason}. `country` omitted or "*" means
    every country - a franchise or dealer network is rarely excluded in one
    market and included in the next.

    A reason is required. An exclusion without one is indistinguishable from
    a typo six months later, and this drops evidence.
    """
    out = []
    for i, rule in enumerate(spec.get("excluded") or []):
        archetype = str(rule.get("archetype") or "").strip().upper()
        reason = str(rule.get("reason") or "").strip()
        if not archetype:
            raise SystemExit(
                f"{spec['slug']}: excluded[{i}] names no archetype")
        if not reason:
            raise SystemExit(
                f"{spec['slug']}: excluded[{i}] ({archetype}) gives no "
                f"reason. An exclusion drops researched evidence, so it has "
                f"to say why.")
        country = str(rule.get("country") or "*").strip().upper() or "*"
        out.append({"country": country, "archetype": archetype,
                    "reason": reason})

    # An exclusion bars RESEARCH from contributing a site type. It does not
    # touch the declared footprint, and the two are not in conflict.
    #
    # This refused the combination at first, on the reasoning that one of
    # them had to be a mistake. UNFI showed otherwise: it operates about 75
    # Cub Foods and Shoppers stores, and its 10-K also states the ~60,000
    # customer locations it SUPPLIES. Both are true, both are STORE, and
    # only one is UNFI's estate. "I operate these, and research will find
    # those" is a coherent thing for a spec to say, so the declared count
    # stands and research is barred from the pair.
    return out


def _excluded_by(rules, country, archetype):
    """The reason this pair is out of scope, or None."""
    country = str(country or "").upper()
    archetype = str(archetype or "").upper()
    for rule in rules:
        if rule["archetype"] == archetype and rule["country"] in ("*", country):
            return rule["reason"]
    return None


def _promotion_record(prom: dict) -> dict:
    """The promotion outcome as the manifest should carry it.

    Counts, and every decline with its reason. `promote` already returns
    both; only the summary was being kept.
    """
    result = (prom or {}).get("result") or {}
    declined = result.get("declined") or []
    return {
        "promoted": (prom or {}).get("promoted"),
        "detail": (prom or {}).get("detail"),
        "offered": len((prom or {}).get("ids") or []),
        "accepted": len(result.get("promoted_footprint") or []),
        # The label and country too, not the reason alone. A manifest
        # reading "sources disagree by 38% (13 to 18)" beside no subject
        # cannot be acted on: Nestle's was its French plant count, and
        # finding that out meant re-deriving it from the triangulated
        # bands.
        "declined": [{"reason": d.get("reason"), "label": d.get("label"),
                      "country": d.get("country"), "flags": d.get("flags")}
                     for d in declined],
        "declined_count": len(declined),
    }


def footprint_for_simulation(case_id, spec):
    """Researched counts where research spoke, disclosed counts where it did
    not, merged on (country, archetype).

    Not one or the other, because both alone are wrong in a different
    direction. The pilot run made the case: for Unilever the agents returned
    seven rows totalling seventeen sites - five GB plants, four DE plants, a
    couple of offices - every one of them a real sourced fact, and together
    not an estate. It had no data centre and almost no offices, because
    nobody publishes a list of them. Priced on its own it produced a baseline
    an order of magnitude under the disclosed footprint, and next to a
    3,900-site grocery estate it would read as "Unilever has a small
    network", which is not what the research found. It is what the research
    could see.

    Taking only the disclosed footprint is the opposite error: it throws away
    the one part of the estate that was actually evidenced.

    So: a researched (country, archetype) replaces the disclosed row for that
    pair, and pairs research did not reach keep theirs. The manifest records
    every row's origin, and the confidence model is unaffected - it reads
    evidence from the dispositions, not from this merge.
    """
    with db.SessionLocal() as s:
        rows = s.execute(select(db.evidenced_footprint).where(
            db.evidenced_footprint.c.case_id == case_id)).all()
    promoted = [r for r in rows if r.promoted_at is not None and r.sites]

    # Only archetypes the simulation knows.
    #
    # It refuses an unknown one with 422 and names it, which is right - a
    # footprint row for an archetype that does not exist would otherwise be
    # priced at the DEFAULT prior and look enumerated. But the refusal lands
    # on the whole company, after its research is paid for, so this driver
    # checks before asking rather than discovering it in a stack trace.
    #
    # Needed because an earlier promotion stored the whole descriptive label
    # as the archetype. Those rows are short enough to fit the column, so
    # they were written rather than rejected, and the fix that stopped
    # producing them could not retract them: promote() deletes by
    # (case_id, country, archetype), and the archetype had changed.
    # Asked per item, not via set(ARCHETYPES). That spelling returned an
    # empty set while `in` answered correctly - see P-16 - and this driver
    # deleted 75 rows of promoted evidence on the strength of it. The type
    # is fixed; asking the question the way the product code asks it is
    # still the safer habit.
    from app.domain.promotion import ARCHETYPES
    unknown = sorted({r.archetype for r in promoted
                      if r.archetype not in ARCHETYPES})
    if unknown:
        log(slug, f"dropping {len(unknown)} footprint row(s) naming an "
                  f"archetype the simulation does not know: "
                  f"{', '.join(repr(u) for u in unknown[:3])}")
    promoted = [r for r in promoted if r.archetype in ARCHETYPES]

    # Site types this company's scope deliberately excludes.
    #
    # A declared footprint says what is IN. It had no way to say what is OUT,
    # and the merge cannot tell "the disclosure does not list this" from "the
    # disclosure excludes this" - it adds any researched pair the disclosure
    # lacks, which is right for a layer nobody published and wrong for one
    # somebody ruled out.
    #
    # UPS is the case that found it. Its spec excluded the franchised UPS
    # Store network in a comment - those are independently owned, and their
    # connectivity is not UPS's cost - and research promoted 5,603 of them,
    # taking the estate from 1,038 sites to 6,692 and pricing retail circuits
    # UPS does not buy. The exclusion was prose in a JSON file; nothing read
    # it.
    #
    # Never silent. What research found is reported with the reason it was
    # not priced, because "we looked and ruled it out" is a finding and
    # dropping it quietly would look identical to never having searched.
    excluded, dropped, excluded_provenance = _scope_exclusions(spec), [], []
    if excluded:
        kept = []
        for r in promoted:
            rule = _excluded_by(excluded, r.country, r.archetype)
            (dropped if rule else kept).append((r, rule) if rule else r)
        promoted = kept
        by_rule = {}
        for r, rule in dropped:
            agg = by_rule.setdefault(
                (r.country, r.archetype), {"sites": 0, "reason": rule})
            agg["sites"] += int(r.sites)
        for (country, archetype), agg in sorted(by_rule.items()):
            excluded_provenance.append({
                "country": country, "archetype": archetype,
                "sites": agg["sites"], "origin": "EXCLUDED_BY_SCOPE",
                "reason": agg["reason"]})
            log(spec["slug"],
                f"excluded {agg['sites']} {country}/{archetype} site(s) "
                f"research found: {agg['reason']}")

    researched = {}
    for r in promoted:
        key = (r.country, r.archetype)
        researched[key] = researched.get(key, 0) + int(r.sites)

    # One pass over the union of the two key sets, so every (country,
    # archetype) is decided once and lands in exactly one place.
    disclosed = {(r["country"], r["archetype"]): int(r["sites"])
                 for r in spec["declared_footprint"]}
    # The declared density band, kept alongside the count.
    #
    # The merge used to build rows as {country, archetype, sites} and drop
    # it. serviceability is keyed (country, density_band, bearer), so a
    # footprint with no density matched nothing, took the "silence, not a
    # constraint" path, and every site in all twenty estimates resolved
    # DELIVERED. The whole serviceability model was inert and nothing said
    # so - the SUBURBAN/URBAN/RURAL bands declared in companies.json were
    # discarded one function before they were needed.
    declared_density = {(r["country"], r["archetype"]): r.get("density")
                        for r in spec["declared_footprint"]}

    # Seeded with what scope ruled out, so an excluded layer is reported
    # beside the rows that were kept rather than only in the run log.
    merged, provenance = [], list(excluded_provenance)
    for key in sorted(set(researched) | set(disclosed)):
        country, archetype = key
        found = researched.get(key)
        said = disclosed.get(key)

        if found is not None and said is None:
            sites, origin = found, "RESEARCHED"
        elif found is None:
            sites, origin = said, "PUBLIC_DISCLOSURE"
        elif found >= said:
            sites, origin = found, "SUPERSEDED_BY_RESEARCH"
        else:
            # Research found fewer than the company discloses, so it saw
            # part of the estate rather than a smaller estate.
            #
            # This used to be "researched always wins", and it produced a
            # 20-site BASF: the agent returned one DE PLANT - Ludwigshafen,
            # named as a single location - and that replaced forty disclosed
            # German plants. Volkswagen came out at 25 sites, Novartis 35,
            # Siemens 44, all the same way. An agent naming an example is
            # not an agent counting an estate, and nothing in the quantity
            # distinguishes the two.
            sites, origin = said, "DISCLOSURE_KEPT_RESEARCH_FOUND_FEWER"

        # A researched pair with no disclosed counterpart has no band:
        # evidenced_footprint carries a count and a source, not a density.
        # Left as None rather than guessed - a density nobody established
        # would silently re-price the estate - and counted below so the
        # gap is visible instead of just quiet.
        density = declared_density.get(key)
        merged.append({"country": country, "archetype": archetype,
                       "sites": int(sites), "density": density})
        row = {"country": country, "archetype": archetype,
               "sites": int(sites), "origin": origin, "density": density}
        # Both numbers, wherever they differ, so the choice is arguable
        # rather than silent.
        if found is not None and said is not None and found != said:
            row["research_said"] = found
            row["disclosure_said"] = said
        provenance.append(row)

    for u in unknown:
        provenance.append({"archetype": u,
                           "origin": "DROPPED_UNKNOWN_ARCHETYPE"})

    if not merged:
        return list(spec["declared_footprint"]), "PUBLIC_DISCLOSURE_ONLY", provenance
    origin = ("RESEARCH_MERGED_WITH_DISCLOSURE" if researched
              else "PUBLIC_DISCLOSURE_ONLY")
    merged, provenance = _fill_bands_from_mix(merged, provenance, spec)
    return merged, origin, provenance


def _fill_bands_from_mix(merged, provenance, spec):
    """Give researched rows a density band from the governed sector mix.

    A researched pair arrives with a country, a type and a count but no band,
    because evidenced_footprint stores a source rather than a density. The
    band is what serviceability is keyed on, so without it the row matches
    nothing and its sites resolve DELIVERED untested.

    reference.density_mix is the governed answer to what bands a sector's
    sites sit in, so it fills them - splitting each counted row across bands
    rather than picking the modal one, because assigning 2,601 agencies to a
    single band overstates what a share actually says.

    Three things it will not do. It does not substitute a site type: a row
    whose type is absent from the sector's mix keeps no band at all, rather
    than borrowing the bands of a type the client was never counted as
    having. It does not touch a declared band, which is a statement about
    this client and outranks a sector norm. And it does not present the
    result as evidence - the filled rows are marked DENSITY_FROM_MIX and
    carry the basis, so a reader can tell a default from a finding.
    """
    no_band = [m for m in merged if not m.get("density")]
    if not no_band:
        return merged, provenance

    industry = (spec.get("industry") or {})
    sector = industry.get("industry") if isinstance(industry, dict) else industry

    out, filled, unfilled, reasons = [], [], [], {}
    for row in merged:
        if row.get("density"):
            out.append(row)
            continue
        with db.SessionLocal() as session:
            split = footprint.density_split_for_archetype(
                session, sites=int(row["sites"]),
                archetype=row["archetype"], industry=sector)
        if not split["rows"]:
            out.append(row)
            unfilled.append(row)
            if split.get("note"):
                reasons[row["archetype"]] = split["note"]
            continue
        for part in split["rows"]:
            out.append({"country": row["country"],
                        "archetype": row["archetype"],
                        "sites": int(part["sites"]),
                        "density": part["density"]})
        entry = {"country": row["country"],
                 "archetype": row["archetype"],
                 "sites": int(row["sites"]),
                 "basis": split["basis"],
                 "mix_industry": split["industry"],
                 "bands": {p["density"]: p["sites"] for p in split["rows"]}}
        # The sector records this layer under another name, so say so rather
        # than leave a STORE wearing a branch network's distribution.
        if split.get("via_layer"):
            entry["via_layer"] = split["via_layer"]
        filled.append(entry)

    if filled:
        provenance.append({
            "origin": "DENSITY_FROM_MIX",
            "rows": len(filled),
            "sites": sum(f["sites"] for f in filled),
            "filled": filled,
            "note": ("the count and the site type are evidenced; the band is "
                     "a governed sector default from reference.density_mix, "
                     "not a finding about this client. It decides which "
                     "bearers are tested, so it is worth replacing with what "
                     "the client actually has.")})
    if unfilled:
        provenance.append({
            "origin": "NO_DENSITY_BAND",
            "rows": len(unfilled),
            "sites": sum(int(m["sites"]) for m in unfilled),
            "reasons": reasons,
            "note": ("these rows carry no density band, so serviceability "
                     "cannot be resolved for them and their sites are "
                     "treated as deliverable. The sector mix has no row for "
                     "their site type, and another type's bands are not "
                     "borrowed.")})
    return out, provenance


def simulate(case_id, slug, footprint):
    st, sim = call("POST", f"/v1/outside-in/cases/{case_id}/simulations:run",
                   {"seed": SEED, "ensemble_size": ENSEMBLE,
                    "footprint": footprint}, timeout=600)
    if st not in (200, 202):
        raise RuntimeError(f"simulation {st}: {sim}")
    sim_id = sim["simulation_run_id"]
    for _ in range(900):
        st, poll = call("GET", f"/v1/outside-in/simulations/{sim_id}",
                        timeout=120)
        if (poll or {}).get("status") in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    if poll.get("status") != "SUCCEEDED":
        raise RuntimeError(f"simulation ended {poll.get('status')}")

    # The row, not the poll. The poll endpoint answers "is it finished?" -
    # status, percent, output_hash, cancel_requested - and carries none of
    # the simulation: not the sites it generated, not the circuits, not the
    # serviceability table, and not the pins saying what it was generated
    # from. A file called simulation.json holding none of that looks like the
    # thing it is missing. tools/backfill_simulation.py repairs runs written
    # before this.
    with db.SessionLocal() as s:
        row = s.execute(select(db.simulation_run).where(
            db.simulation_run.c.simulation_run_id == sim_id)).first()
    out = dict(row.output or {})
    # Per-site arrays: tens of thousands of rows on a large estate, and the
    # same information the aggregates already carry.
    omitted = [f"{k} ({len(out[k])} rows)" for k in ("estate", "sample_topology")
               if k in out]
    for k in ("estate", "sample_topology"):
        out.pop(k, None)

    record = {
        "simulation_run_id": row.simulation_run_id, "case_id": row.case_id,
        "model_version": row.model_version, "seed": row.seed,
        "ensemble_size": row.ensemble_size, "status": row.status,
        "output_hash": row.output_hash, "started_at": row.started_at,
        "ended_at": row.ended_at, "params": row.params,
        "pinned_priors": row.pinned_priors, "output": out,
    }
    if omitted:
        record["output_omitted"] = {
            "fields": omitted,
            "why": ("per-site arrays, the same information the aggregates "
                    "carry; tools/backfill_simulation.py --full keeps them"),
        }
    log(slug, f"simulation {row.status}, {out.get('sites')} sites, "
              f"{(out.get('circuits') or {}).get('base')} circuits")
    return sim_id, record


def estimate(case_id, slug, sim_id, footprint):
    total_sites = sum(int(r["sites"]) for r in footprint)
    st, est = call("POST", f"/v1/outside-in/cases/{case_id}/estimates:run", {
        "method": "BUILD_UP", "simulation_run_id": sim_id,
        # Both are inputs the model will not invent. Stated here, recorded in
        # the manifest, and deliberately crude: a per-site operating cost and
        # a user population nobody has researched are assumptions, and the
        # confidence model is what carries that.
        "users": max(1, total_sites * 12),
        "ops_cost_per_site_base": 900}, timeout=900)
    if st != 200:
        raise RuntimeError(f"estimate {st}: {est}")
    log(slug, f"V0 {est.get('v0_status')}, "
              f"baseline {(est.get('current_tco') or {}).get('base')}")
    return est


# ------------------------------------------------------------- what we store
def fx_to_eur(currency):
    """The rate used to make a figure comparable, and the date it is from.

    CR-09. Captured at run time from reference.fx_rate rather than computed
    in the summary, because a rate without the date it was read on is not a
    rate. Local currency stays the source of truth; the EUR column is
    derived and says so.
    """
    cur = (currency or "").upper()
    if cur == "EUR":
        return {"rate": "1.0", "as_of": None, "basis": "base currency",
                "evidence_grade": None, "source": "identity"}
    def _grade(*rows):
        """The weakest leg governs. A cross-rate is no better evidenced than
        its worst half, and reporting the better grade would make a derived
        rate look stronger than either number behind it."""
        order = ["A", "B", "C", "D", "E", "F"]
        grades = [getattr(r, "evidence_grade", None) for r in rows]
        found = [g for g in grades if g in order]
        return max(found, key=order.index) if found else None

    def _oldest(*rows):
        """A rate is only as fresh as its stalest leg."""
        dates = [str(getattr(r, "as_of", "") or "") for r in rows]
        real = [d for d in dates if d]
        return min(real) if real else None

    with db.SessionLocal() as s:
        row = s.execute(select(db.fx_rate).where(
            db.fx_rate.c.from_currency == cur,
            db.fx_rate.c.to_currency == "EUR")).first()
        if row is None:
            row = s.execute(select(db.fx_rate).where(
                db.fx_rate.c.from_currency == "EUR",
                db.fx_rate.c.to_currency == cur)).first()
            if row is not None:
                r = D(str(row.rate))
                return {"rate": str(D(1) / r) if r else None,
                        "as_of": str(getattr(row, "as_of", "") or ""),
                        "basis": f"inverted EUR->{cur}",
                        "evidence_grade": getattr(row, "evidence_grade", None),
                        "source": getattr(row, "source", None),
                        "convention": getattr(row, "convention", None)}

        if row is None:
            # A cross-rate through the table's own base, where both legs
            # exist. reference.fx_rate is USD-quoted - every row is USD->X -
            # so only USD had a direct line to EUR, and CHF and GBP figures
            # went out as DECLARED_UNKNOWN while USD->CHF, USD->GBP and
            # USD->EUR were all sitting in the table. Three of twenty
            # companies could not be compared for want of one division.
            #
            # Arithmetic on two governed rates, not a new number: both legs
            # are named, the date is the older of the two and the grade the
            # weaker, because a derived rate must not read as fresher or
            # better evidenced than the figures behind it.
            for base in ("USD", "EUR"):
                if base == cur:
                    continue
                leg_cur = s.execute(select(db.fx_rate).where(
                    db.fx_rate.c.from_currency == base,
                    db.fx_rate.c.to_currency == cur)).first()
                leg_eur = s.execute(select(db.fx_rate).where(
                    db.fx_rate.c.from_currency == base,
                    db.fx_rate.c.to_currency == "EUR")).first()
                if not (leg_cur and leg_eur):
                    continue
                rc, re_ = D(str(leg_cur.rate)), D(str(leg_eur.rate))
                if rc == 0:
                    continue
                return {
                    "rate": str(re_ / rc),
                    "as_of": _oldest(leg_cur, leg_eur),
                    "basis": f"cross-rate via {base}",
                    "legs": [f"{base}->{cur}={leg_cur.rate}"
                             f"@{getattr(leg_cur, 'as_of', '') or '?'}",
                             f"{base}->EUR={leg_eur.rate}"
                             f"@{getattr(leg_eur, 'as_of', '') or '?'}"],
                    "evidence_grade": _grade(leg_cur, leg_eur),
                    "source": "derived from reference.fx_rate",
                    "convention": getattr(leg_eur, "convention", None)}
    if row is None:
        # Declared, not guessed. A missing rate makes the EUR column unknown,
        # not approximate.
        return {"rate": None, "as_of": None, "basis": "DECLARED_UNKNOWN",
                "evidence_grade": None, "source": None}
    return {"rate": str(row.rate),
            "as_of": str(getattr(row, "as_of", "") or ""),
            "basis": f"{cur}->EUR",
            # The seeded rates say of themselves: "indicative: nobody looked
            # this up, and an estimate converted at it should say so."
            # Carrying grade and source is how it says so.
            "evidence_grade": getattr(row, "evidence_grade", None),
            "source": getattr(row, "source", None),
            "convention": getattr(row, "convention", None)}


def scope_report(spec, foot, foot_prov):
    """What the modelled estate covers, and what it does not.

    CR-02a. The output used to present a three-country baseline exactly as it
    presents a group one. Nothing in it said which, and a reader could not
    tell a deliberate partial scope from a failed enumeration.

    The company's full country count is not sourced here, so it is reported
    DECLARED_UNKNOWN rather than estimated. Scaling an in-scope baseline to a
    group figure by an unsourced factor is the thing principle 1 forbids.
    """
    modelled = sorted({r["country"] for r in foot})
    by_type = {}
    for p in foot_prov:
        a = p.get("archetype")
        if not a or p.get("origin") == "DROPPED_UNKNOWN_ARCHETYPE":
            continue
        by_type.setdefault(a, set()).add(p.get("origin"))
    sites_origin = {
        a: ("RESEARCHED" if o & {"RESEARCHED", "SUPERSEDED_BY_RESEARCH"}
            else "ASSUMED_PUBLIC_DISCLOSURE")
        for a, o in sorted(by_type.items())}
    return {
        "scope_countries_modelled": modelled,
        "scope_countries_company_total": "DECLARED_UNKNOWN",
        "scope_status": ("PARTIAL_COUNTRIES" if modelled else "UNKNOWN"),
        "scope_note": (
            f"Baseline covers {len(modelled)} country(ies) "
            f"({', '.join(modelled)}) and the site types listed in "
            f"sites_origin. The group's full country and site-type count is "
            f"not sourced, so the share of the group this represents is "
            f"DECLARED_UNKNOWN. This is baseline_in_scope, not a group "
            f"baseline."),
        "sites_origin": sites_origin,
    }


def harvest(case_id, research_raw, prior_timings=None):
    """The research, as findings rather than as agent runs.

    `prior_timings` is what a previous run recorded for this company, so a
    resumed or repromoted run reports the case's research time rather than
    this session's - which is zero whenever no domain was called.
    """
    with db.SessionLocal() as s:
        disp = [dict(r._mapping) for r in s.execute(
            select(db.domain_disposition).where(
                db.domain_disposition.c.case_id == case_id)).all()]
        facts = [dict(r._mapping) for r in s.execute(
            select(db.known_fact).where(
                db.known_fact.c.case_id == case_id)).all()]
        foot = [dict(r._mapping) for r in s.execute(
            select(db.evidenced_footprint).where(
                db.evidenced_footprint.c.case_id == case_id)).all()]

    by_no = {d["domain_no"]: d for d in disp}
    highlights = {}
    for n, key in HIGHLIGHT_DOMAINS.items():
        d = by_no.get(n) or {}
        ev = d.get("evidence") or {}
        highlights[key] = {
            "domain_no": n,
            "domain": dict(dispositions.DOMAINS).get(n),
            "disposition": d.get("disposition"),
            "reason": d.get("reason"),
            # There is no "finding" key on the evidence and there never was
            # - a disposition stores sources, quantities, triangulated bands,
            # qualitative findings, reliability and conflicts. Reading a key
            # that does not exist gave every highlight a None finding, and
            # the summary then printed the disposition and nothing else for
            # companies holding seven sources and eight quantities.
            #
            # `triangulated` is the one worth leading on: it carries the band
            # and the vintage, which is the difference between "Allianz has
            # 34 branches in FR" and a figure somebody can argue with.
            "quantities": ev.get("quantities") if isinstance(ev, dict) else None,
            "triangulated": ev.get("triangulated") if isinstance(ev, dict) else None,
            "qualitative": ev.get("qualitative") if isinstance(ev, dict) else None,
            "conflicts": ev.get("conflicts") if isinstance(ev, dict) else None,
            "reliability": ev.get("reliability") if isinstance(ev, dict) else None,
            "sources": ([{"url": sc.get("url"),
                          "publisher": sc.get("publisher"),
                          "as_of": sc.get("as_of"),
                          "source_class": sc.get("source_class")}
                         for sc in (ev.get("sources") or [])]
                        if isinstance(ev, dict) else None),
        }
    return {
        "highlights": highlights,
        "dispositions": disp,
        "known_facts": facts,
        "evidenced_footprint": foot,
        # Cumulative for the case, not for this session.
        #
        # research_raw holds what THIS run researched, and a --repromote run
        # researches nothing - so a company with 48 sources exported zero
        # minutes beside them, which an audit flagged on five of six rows.
        # The number was accurate about the session and wrong about the
        # question a reader asks next to a source count.
        #
        # Prior timings are carried forward and this run's overwrite per
        # domain, so a repaired domain reports its new time and the rest keep
        # theirs.
        "timings_seconds": {**(prior_timings or {}),
                            **{str(k): v["seconds"]
                               for k, v in research_raw.items()}},
    }


def write(outdir, slug, payload):
    d = outdir / slug
    d.mkdir(parents=True, exist_ok=True)
    for name, body in payload.items():
        (d / f"{name}.json").write_text(
            json.dumps(body, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8")
    return d


def run_one(spec, outdir, domains, force, repair=False, repromote=False, redo=False):
    slug = spec["slug"]
    done = outdir / slug / "estimate_v0.json"
    if (done.exists() and not force and not repair and not repromote
            and not redo):
        print(f"[skip] {slug}: already has results")
        return json.loads((outdir / slug / "manifest.json").read_text("utf-8"))

    print(f"\n=== {spec['legal_name']} ({spec['industry']}) ===", flush=True)
    t0 = time.time()

    prior = ledger_read(outdir).get(slug)
    resumed = bool(prior and case_is_usable(prior))
    if repromote and not resumed:
        # Nothing to re-offer. Refused rather than quietly starting a fresh
        # case, which would spend money this mode exists to avoid.
        raise RuntimeError(
            f"{slug}: --repromote needs an existing confirmed case and the "
            f"ledger has none")
    if resumed:
        case_id, done_before = prior, researched_domains(prior)
        log(slug, f"resuming case {case_id}: "
                  f"{len(done_before)} domain(s) already researched")
        ent = {"resolved": None, "resumed": True}
        # Pre-flight is re-run on a resumed case, not skipped.
        #
        # The simulation gates on the stored report, not on live case state,
        # so skipping this left whatever report the first attempt wrote. For
        # inditex, mcdonalds and rio-tinto that was a report raising BLOCK on
        # "Entity resolution, Mandatory intake" - conditions since repaired
        # on the case itself, and still refusing the simulation three runs
        # later because nothing had asked the question again.
        pf = preflight(case_id)
    else:
        done_before = set()
        case_id = intake(spec)
        ledger_write(outdir, slug, case_id)
        log(slug, f"case {case_id}")
        ent = resolve_and_confirm(case_id, spec)
        log(slug, f"entity resolved={ent['resolved']}"
                  + (" (fallback confirmation)"
                     if ent.get("confirmed_by_fallback") else ""))
        pf = preflight(case_id)

    ind = set_industry_if_absent(case_id, spec)
    log(slug, f"industry {ind['industry']} ({ind['origin']})")
    if ind["origin"] == "CASE_RECORD":
        log(slug, f"!! INDUSTRY NOT THE SPEC'S: the case holds "
                  f"{ind['industry']} and the spec says {spec['industry']}. "
                  f"The case's code prices the estate; correct whichever "
                  f"is wrong.")
    if ind.get("agrees_with_resolution") is False:
        # Loud, because the quiet version of this cost seventeen research
        # calls and an estimate priced on the wrong archetype bandwidth.
        log(slug, f"!! INDUSTRY DISAGREEMENT: the case is "
                  f"{ind['industry']} and the resolver called this entity "
                  f"{ind['resolution_said']!r}. One of them is wrong and "
                  f"the code is what prices the estate.")

    disp_out = dispose_analyst_domains(case_id, slug, domains,
                                       keep=done_before)
    # Research skips these itself, but asking for them anyway would still
    # cost a round trip each and muddy the log.
    if repromote:
        # No provider calls at all. Re-runs promotion, the footprint merge,
        # the simulation and the estimate against research already paid for.
        #
        # Needed because the classifier that decides which findings the
        # estimate may consume was reading a whole label where it should have
        # read the leading token, so an agent that described its mapping -
        # which the prompt asks it to do - produced findings the estimate
        # never saw. Fixing that changes what promotion offers, and the only
        # way to apply it to work already done is to ask again.
        todo = []
        log(slug, f"re-promote: no research, re-offering findings from "
                  f"{len(done_before)} researched domain(s)")
        raw = {}
    elif repair:
        # Only the domains the net disposed, and overwrite so research does
        # not skip them. Targeted rather than a blanket overwrite: a company
        # with twelve good domains and five fallbacks should re-buy five.
        todo = fell_back_domains(case_id, domains)
        log(slug, f"repair: re-researching {len(todo)} domain(s) the "
                  f"fallback disposed, keeping {len(done_before)} researched")
        raw = do_research(case_id, slug, todo, overwrite=True)
    elif redo:
        # Re-buy the domains named on --domains, whatever they already hold.
        #
        # --repair re-researches only what the fallback disposed, and the
        # default path skips anything already carrying a verdict. Neither
        # can ask a domain the same question twice, which is what you want
        # when the brief was tightened or the answers came back unusable:
        # domain 19 held German and French prices of 29.95 and 29.99 a
        # month, consumer fibre promotions with no bandwidth tier, which
        # its own brief discards on sight. The domain was answered and the
        # answer was worthless, and nothing could ask again.
        log(slug, f"redo: re-researching {len(domains)} domain(s) "
                  f"{sorted(domains)} over whatever they already hold")
        raw = do_research(case_id, slug, domains, overwrite=True)
    else:
        todo = [n for n in domains if n not in done_before]
        if len(todo) != len(domains):
            log(slug, f"skipping {len(domains) - len(todo)} domain(s) "
                      f"already researched on this case")
        raw = do_research(case_id, slug, todo)
    # A retryable failure is worth retrying before it becomes a gap. The DNS
    # outage that cost Fraport twelve domains lasted under a minute per call
    # and had recovered by the time domain 18 ran - the run simply never
    # looked back. Two passes with a wait between them, because a provider
    # blip and a provider outage look identical on the first attempt.
    blocked = transport_blocked(raw)
    for attempt in (1, 2):
        if not blocked:
            break
        log(slug, f"retry {attempt}: {len(blocked)} domain(s) blocked on "
                  f"infrastructure {sorted(blocked)}, waiting "
                  f"{BLOCKED_RETRY_WAIT}s")
        time.sleep(BLOCKED_RETRY_WAIT)
        again = do_research(case_id, slug, sorted(blocked), overwrite=True)
        for n, got in again.items():
            raw[n] = got
        blocked = transport_blocked(again)
    if blocked:
        log(slug, f"{len(blocked)} domain(s) still blocked after 2 retries: "
                  + ", ".join(f"{n} {k}" for n, k in sorted(blocked.items())))

    fell_back = dispose_unanswered(case_id, slug, blocked=blocked)
    # Refusing here rather than publishing is the point of the whole change.
    # An estimate assembled over domains that never reached the provider is
    # not a thin estimate, it is an estimate about nothing, and the manifest
    # that labels its domains BENCHMARK_PRIOR cannot say which were a
    # considered fallback and which were an outage. Failing the company makes
    # the gap visible and leaves the domains undisposed so --repair can buy
    # them back.
    if blocked:
        raise RuntimeError(
            f"research never reached the provider for {len(blocked)} "
            f"domain(s) ({', '.join(f'{n} {k}' for n, k in sorted(blocked.items()))}). "
            f"These are infrastructure failures, not research outcomes, so "
            f"they are left undisposed rather than recorded as BENCHMARK_PRIOR. "
            f"Re-run this company when the provider is reachable.")

    prom = promote(case_id, slug)

    foot, foot_origin, foot_prov = footprint_for_simulation(case_id, spec)
    n_res = sum(1 for p in foot_prov if p["origin"] == "RESEARCHED")
    _nb = sum(1 for r in foot if not r.get("density"))
    log(slug, f"footprint: {foot_origin}, {sum(r['sites'] for r in foot)} "
              f"sites, {n_res} row(s) from research"
              + (f", {_nb} row(s) with no density band" if _nb else ""))

    sim_id, sim = simulate(case_id, slug, foot)
    est = estimate(case_id, slug, sim_id, foot)
    # What a previous run already recorded, so a repromote does not report
    # zero minutes beside a source count it did not gather this session.
    _prior = {}
    _existing = outdir / slug / "research.json"
    if _existing.exists():
        try:
            _prior = (json.loads(_existing.read_text("utf-8"))
                      .get("timings_seconds") or {})
        except (OSError, ValueError):
            _prior = {}
    res = harvest(case_id, raw, prior_timings=_prior)

    manifest = {
        "slug": slug,
        "legal_name": spec["legal_name"],
        "industry": ind,
        "domicile": spec["domicile"],
        "in_scope_countries": spec["countries"],
        "base_currency": spec["currency"],
        "case_id": case_id,
        # Which spec produced this, so an artifact can be traced back to the
        # input that made it. A stale spec once rewrote six companies' scope
        # with nothing in any output naming the file it had read.
        "spec_path": str(SPEC_IDENTITY.get("path") or ""),
        "spec_sha256": SPEC_IDENTITY.get("digest") or "",
        "entity_resolution": ent,
        "resumed_existing_case": resumed,
        "mode": ("repromote" if repromote else "repair" if repair else "run"),
        "domains_already_researched_on_resume": sorted(done_before),
        "footprint_origin": foot_origin,
        "footprint_used": foot,
        # Row by row: what research found, what it superseded, and what rests
        # on disclosure alone. The single largest driver of the baseline, so
        # it is recorded at the level someone can argue with.
        "footprint_provenance": foot_prov,
        # CR-02a: what this baseline covers, stated rather than implied.
        **scope_report(spec, foot, foot_prov),
        # CR-09: local currency is the source of truth; this makes the
        # EUR column derivable and dated.
        "fx_to_eur": fx_to_eur(spec["currency"]),
        "seed": SEED,
        "ensemble_size": ENSEMBLE,
        # What was asked for, and what came back with an agent verdict.
        # The first overstates coverage whenever a call fails, and a manifest
        # that overstates its own research is the thing this set is least
        # allowed to do.
        # CR-01. A domain the agent never answered is not researched, and a
        # domain disposed BENCHMARK_PRIOR is not evidenced. The summary used
        # to report domains_declared_unknown as 0 for almost every company
        # while most of their domains had no evidence behind them.
        "domains_declared_unknown": sorted(
            set(domains) - set(researched_domains(case_id))),
        "domains_requested": domains,
        "domains_fell_back_unanswered": fell_back["fell_back"],
        "domains_researched": sorted(researched_domains(case_id)),
        "estimate_inputs": {
            "method": "BUILD_UP",
            "users": max(1, sum(int(r["sites"]) for r in foot) * 12),
            "ops_cost_per_site_base": 900,
            "note": ("users and ops_cost_per_site are assumptions, not "
                     "research. They are stated here because an estimate "
                     "that hides its inputs cannot be checked."),
        },
        # _version.BUILD, the single source of release identity. This read
        # config.VERSION, which does not exist, so every manifest in the
        # first run recorded build: null - a run that cannot say which code
        # produced it is not reproducible, which is most of the point of
        # writing a manifest at all.
        "build": _version.BUILD,
        "run_started": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
        "run_seconds": round(time.time() - t0, 1),
        "preflight_conditions": len(pf.get("conditions") or []),
        # What promotion accepted AND what it refused, with the reasons.
        #
        # This recorded only {promoted: true, detail: null} and dropped the
        # result, so a candidate research had found and promotion had
        # declined left no trace anywhere. Boots is the case: research
        # returned 2,164 GB stores, no GB/STORE row reached the footprint,
        # and nothing in the artifact said whether it was a conflict, a
        # duplicate or a bug. A decline is a decision about evidence and has
        # to be as visible as an acceptance.
        "promotion": _promotion_record(prom),
        "domains_benchmark_disposed": [n for n, _ in dispositions.DOMAINS
                                       if n not in set(domains)],
        "domains_with_no_agent": ANALYST_DOMAINS,
        "analyst_disposition_response": {
            "stored": disp_out.get("stored"),
            "provenance_dropped": disp_out.get("provenance_dropped"),
        },
    }

    write(outdir, slug, {
        "manifest": manifest,
        "simulation": sim,
        "estimate_v0": est,
        "research": res,
    })
    log(slug, f"done in {manifest['run_seconds']}s")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--domains", default="")
    ap.add_argument("--redo", action="store_true",
                    help="re-research the domains given in --domains, "
                         "overwriting what they already hold. For when the "
                         "brief changed or the answers were unusable.")
    ap.add_argument("--repair", action="store_true",
                    help="re-research only domains the fallback disposed")
    ap.add_argument("--repromote", action="store_true",
                    help="no provider calls: re-offer findings already paid "
                         "for, then re-simulate and re-estimate")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--spec", default="",
                    help="path to companies.json. Never read from --out: see "
                         "resolve_spec for what that cost.")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    spec_path = resolve_spec(args.spec, outdir)
    spec_doc = spec_path.read_text("utf-8")
    spec_digest = hashlib.sha256(spec_doc.encode("utf-8")).hexdigest()[:12]
    SPEC_IDENTITY.update(path=spec_path, digest=spec_digest)
    specs = json.loads(spec_doc)["companies"]
    print(f"spec {spec_path} sha256:{spec_digest} "
          f"({len(specs)} companies, "
          f"{sum(len(s['declared_footprint']) for s in specs)} declared rows)",
          flush=True)
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        specs = [s for s in specs if s["slug"] in want]
    domains = ([int(x) for x in args.domains.split(",") if x.strip()]
               if args.domains else AGENT_DOMAINS)

    print(f"{len(specs)} company(ies), domains {domains}", flush=True)
    results, failures = [], []
    for spec in specs:
        try:
            results.append(run_one(spec, outdir, domains, args.force, repair=args.repair, repromote=args.repromote, redo=args.redo))
        except Exception as exc:                             # noqa: BLE001
            # One company failing is one company, not the run. Named and
            # carried so the set can be completed and the gap is visible.
            print(f"[FAIL] {spec['slug']}: {type(exc).__name__}: {exc}",
                  flush=True)
            failures.append({"slug": spec["slug"], "error": str(exc)})

    (outdir / "_run_log.json").write_text(json.dumps(
        {"completed": [r["slug"] for r in results], "failures": failures,
         "finished": datetime.now(timezone.utc).isoformat()},
        indent=2), encoding="utf-8")
    print(f"\ncompleted {len(results)}, failed {len(failures)}")
    # The status code has to say what the last line says. This returned
    # nothing, so a run printing "completed 1, failed 8" - a DNS outage that
    # took out eight of nine companies - exited 0, and so did a run that
    # could not even open this file because the path had been mangled. A
    # caller checking $? was told both succeeded.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
