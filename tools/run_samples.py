"""Run the outside-in workflow end to end for each company in
samples/outside_in/companies.json, and store what it produced.

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
import json
import pathlib
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import select

from app import _version, db
from app.domain import dispositions, research

API = "http://127.0.0.1:8000"

# The seventeen domains a research agent is routed to. The other seven are
# analyst or policy domains with no agent behind them, so asking for them
# would be a call that cannot answer.
AGENT_DOMAINS = sorted(n for n, a in research.DOMAIN_AGENT_MAP.items() if a)

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

    The candidate carries the industry, and the industry keys
    archetype_bandwidth and archetype_resilience - so an entity confirmed
    without one is an estate priced off DEFAULT. Falls back to the spec's
    industry only if resolution produces nothing, and says which was used.
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
    """The seeded industry code, if resolution did not supply one.

    Recorded in the manifest either way. An industry the seed does not know
    silently falls back to DEFAULT and the estate stops differentiating, so
    this is not a cosmetic field.
    """
    from sqlalchemy import update
    with db.SessionLocal() as s:
        row = s.execute(select(db.case.c.industry).where(
            db.case.c.case_id == case_id)).scalar()
        known = {r[0] for r in s.execute(
            select(db.archetype_bandwidth.c.industry)).all()}
        if row and row.upper() in known:
            return {"industry": row, "origin": "ENTITY_RESOLUTION"}
        s.execute(update(db.case).where(db.case.c.case_id == case_id)
                  .values(industry=spec["industry"]))
        s.commit()
        return {"industry": spec["industry"],
                "origin": "SPEC_FALLBACK",
                "resolution_said": row}


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
            disp = str((got[0] or {}).get("disposition") or "-") if got else "-"
            log(slug, f"domain {n:>2} {name[:34]:<34} {disp:<18} {took}s")
        else:
            log(slug, f"domain {n:>2} {name[:34]:<34} FAILED {st} ({took}s)")
    return out


def dispose_analyst_domains(case_id, slug, researching):
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
    todo = [n for n, _ in dispositions.DOMAINS if n not in set(researching)]
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
              f"ahead of research")
    return out


def dispose_unanswered(case_id, slug):
    """Whatever research could not answer falls back to the seeded prior.

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
    missing = [n for n, _ in dispositions.DOMAINS if n not in have]
    if not missing:
        return {"fell_back": []}
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
    return {"fell_back": missing}


def promote(case_id, slug):
    st, cands = call("GET",
                     f"/v1/outside-in/cases/{case_id}/research-findings",
                     timeout=300)
    if st != 200:
        return {"promoted": False, "detail": f"{st}: {cands}"}
    # footprint_candidates, and candidate_id - the bucket names and the id
    # field are promotion.candidates()' own, not guesses.
    ids = [c.get("candidate_id")
           for c in (cands or {}).get("footprint_candidates") or []]
    ids = [i for i in ids if i]
    if not ids:
        return {"promoted": False, "detail": "no footprint candidates",
                "candidates": cands}
    st, res = call("POST",
                   f"/v1/outside-in/cases/{case_id}/research-findings:promote",
                   {"candidate_ids": ids, "promoted_by": ANALYST},
                   timeout=600)
    log(slug, f"promote {len(ids)} footprint finding(s): {st}")
    return {"promoted": st == 200, "ids": ids, "result": res}


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

    researched = {}
    for r in promoted:
        key = (r.country, r.archetype)
        researched[key] = researched.get(key, 0) + int(r.sites)

    merged, provenance = [], []
    dropped_unknown = unknown
    for key, sites in sorted(researched.items()):
        country, archetype = key
        merged.append({"country": country, "archetype": archetype,
                       "sites": sites})
        provenance.append({"country": country, "archetype": archetype,
                           "sites": sites, "origin": "RESEARCHED"})

    for row in spec["declared_footprint"]:
        key = (row["country"], row["archetype"])
        if key in researched:
            provenance.append(
                {**row, "origin": "SUPERSEDED_BY_RESEARCH",
                 "research_said": researched[key]})
            continue
        merged.append(dict(row))
        provenance.append({**row, "origin": "PUBLIC_DISCLOSURE"})

    if not merged:
        return list(spec["declared_footprint"]), "PUBLIC_DISCLOSURE_ONLY", []
    origin = ("RESEARCH_MERGED_WITH_DISCLOSURE" if researched
              else "PUBLIC_DISCLOSURE_ONLY")
    for u in dropped_unknown:
        provenance.append({"archetype": u, "origin": "DROPPED_UNKNOWN_ARCHETYPE"})
    return merged, origin, provenance


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
def harvest(case_id, research_raw):
    """The research, as findings rather than as agent runs."""
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
        "timings_seconds": {str(k): v["seconds"]
                            for k, v in research_raw.items()},
    }


def write(outdir, slug, payload):
    d = outdir / slug
    d.mkdir(parents=True, exist_ok=True)
    for name, body in payload.items():
        (d / f"{name}.json").write_text(
            json.dumps(body, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8")
    return d


def run_one(spec, outdir, domains, force, repair=False, repromote=False):
    slug = spec["slug"]
    done = outdir / slug / "estimate_v0.json"
    if done.exists() and not force and not repair and not repromote:
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

    disp_out = dispose_analyst_domains(case_id, slug, domains)
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
    else:
        todo = [n for n in domains if n not in done_before]
        if len(todo) != len(domains):
            log(slug, f"skipping {len(domains) - len(todo)} domain(s) "
                      f"already researched on this case")
        raw = do_research(case_id, slug, todo)
    fell_back = dispose_unanswered(case_id, slug)
    prom = promote(case_id, slug)

    foot, foot_origin, foot_prov = footprint_for_simulation(case_id, spec)
    n_res = sum(1 for p in foot_prov if p["origin"] == "RESEARCHED")
    log(slug, f"footprint: {foot_origin}, {sum(r['sites'] for r in foot)} "
              f"sites, {n_res} row(s) from research")

    sim_id, sim = simulate(case_id, slug, foot)
    est = estimate(case_id, slug, sim_id, foot)
    res = harvest(case_id, raw)

    manifest = {
        "slug": slug,
        "legal_name": spec["legal_name"],
        "industry": ind,
        "domicile": spec["domicile"],
        "in_scope_countries": spec["countries"],
        "base_currency": spec["currency"],
        "case_id": case_id,
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
        "seed": SEED,
        "ensemble_size": ENSEMBLE,
        # What was asked for, and what came back with an agent verdict.
        # The first overstates coverage whenever a call fails, and a manifest
        # that overstates its own research is the thing this set is least
        # allowed to do.
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
        "promotion": {"promoted": prom.get("promoted"),
                      "detail": prom.get("detail")},
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
    ap.add_argument("--repair", action="store_true",
                    help="re-research only domains the fallback disposed")
    ap.add_argument("--repromote", action="store_true",
                    help="no provider calls: re-offer findings already paid "
                         "for, then re-simulate and re-estimate")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    specs = json.loads((outdir / "companies.json").read_text("utf-8"))["companies"]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        specs = [s for s in specs if s["slug"] in want]
    domains = ([int(x) for x in args.domains.split(",") if x.strip()]
               if args.domains else AGENT_DOMAINS)

    print(f"{len(specs)} company(ies), domains {domains}", flush=True)
    results, failures = [], []
    for spec in specs:
        try:
            results.append(run_one(spec, outdir, domains, args.force, repair=args.repair, repromote=args.repromote))
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


if __name__ == "__main__":
    main()
