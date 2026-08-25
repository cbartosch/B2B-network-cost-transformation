"""V1 questionnaire and LLM-02 prefill (Tranche 3, first slice).

**This is the prefill half of LLM-02 only.** The registry describes LLM-02 as
"questionnaire prefill and evidence mapping" - two different jobs. Prefill
proposes a likely answer from evidence the system already holds, which is a
suggestion nobody has to accept. Evidence mapping decides what a client's
answer *does* to an existing domain disposition, which requires knowing where
a client-supplied fact sits in the 0.3A disposition taxonomy - and it does not
sit anywhere in it. The six dispositions are EVIDENCED_PUBLIC and
DERIVED_PUBLIC (public evidence), BENCHMARK_PRIOR and SIMULATED (the model's
own priors and draws), ANALYST_ASSERTED_PRIOR (an analyst's unverified
recollection, which known_facts.py caps deliberately), and DECLARED_UNKNOWN.
A client telling you the site count for their own estate is none of those.
Forcing it into ANALYST_ASSERTED_PRIOR would be wrong in the direction that
matters - it would understate first-party data - and inventing a seventh
disposition is a spec decision with confidence-weighting consequences in
estimate.py and confidence.py, not an implementation detail to settle in a
module docstring. So: answers are stored, attributed and reported. Nothing
here writes a disposition or moves a published number.

**Prefill is a suggestion, never an answer.** prefill_value and answer_value
are separate columns and the readiness gate counts only the latter. A
questionnaire that has been prefilled and not returned is, correctly, zero
answers. There is no path in this module by which a prefill becomes an answer
without a named person at the client supplying it.

**Two labels, same discipline as Tranche 2.** LIVE prefill is LLM_PROPOSED;
DETERMINISTIC_ONLY prefill is DETERMINISTIC_PROPOSED. LLM-02 is not one of
the three agents the spec requires DETERMINISTIC_ONLY for (03, 06, 07), so
this build registers it LIVE-only and deterministic_prefill() exists as an
ordinary function callable without an agent run - used when no provider is
configured and the caller asks for it explicitly. It proposes nothing it
cannot source: a question whose domain has no evidenced disposition gets no
prefill at all rather than a plausible guess.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .. import db
from ..llm import errors, gateway, registry
from . import dispositions

log = logging.getLogger("workbench.questionnaire")

# The V1 question set. Keyed to the 0.3A input domain each question informs,
# so a prefill has somewhere to look and an answer has somewhere to be mapped
# later, once the taxonomy question above is settled.
#
# Deliberately short. A real V1 questionnaire is far longer; this is the set
# that maps onto domains this build actually models, rather than a plausible
# -looking list of questions whose answers nothing could consume.
QUESTIONS = [
    ("site_count", "How many sites are in scope, by country?", 2),
    ("site_archetypes", "How would you categorise those sites (HQ, large office, "
                        "small office, plant, data centre)?", 3),
    ("bandwidth_profile", "What access bandwidth is typical at each site type?", 4),
    ("remote_users", "How many remote and office-based users need connectivity?", 5),
    ("dc_cloud_footprint", "Which data centres and cloud regions carry your "
                           "workloads?", 6),
    ("current_architecture", "What is the current WAN architecture (MPLS, DIA, "
                             "SD-WAN, hybrid)?", 7),
    ("current_vendors", "Which carriers and equipment vendors are currently "
                        "contracted?", 8),
    ("contract_events", "When do the principal network contracts expire or renew?", 12),
    ("resilience_posture", "Which sites require dual access, and what is the "
                           "current standard?", 17),
]

QUESTION_KEYS = {q[0] for q in QUESTIONS}

_PREFILL_SHAPE = '{"prefill_value": str|null, "basis": str}'

_PREFILL_SYSTEM_PROMPT = (
    "You are drafting a suggested answer to one question on a client "
    "questionnaire, from evidence the system has already gathered about that "
    "client. This is a suggestion the client will review and correct - never "
    "presented to them as fact, and never counted as their answer. Propose a "
    "value only if the supplied evidence actually supports one. If it does "
    'not, set prefill_value to null and say so in basis: an unsupported '
    "guess wastes the client's time and damages their trust in everything "
    "else on the form. Respond with a single JSON object and nothing else, "
    f"matching this shape exactly: {_PREFILL_SHAPE}.")


def create(session, *, case_id: str) -> dict:
    """Creates the V1 questionnaire for a case. Idempotent per question: a
    second call adds any question missing from an existing questionnaire and
    leaves answered items untouched, rather than deleting and re-inserting
    the way PUT .../domain-dispositions does. Answers are client-supplied and
    must never be destroyed by an operator re-running setup."""
    case_row = session.execute(
        select(db.case.c.case_id).where(db.case.c.case_id == case_id)).one_or_none()
    if case_row is None:
        raise LookupError(f"no such case: {case_id}")

    existing = {r.question_key for r in session.execute(
        select(db.questionnaire_item.c.question_key).where(
            db.questionnaire_item.c.case_id == case_id)).all()}

    created = 0
    for key, text, domain_no in QUESTIONS:
        if key in existing:
            continue
        try:
            session.execute(insert(db.questionnaire_item).values(
                item_id=str(uuid.uuid4()), case_id=case_id, question_key=key,
                question_text=text, domain_no=domain_no))
            session.commit()
            created += 1
        except IntegrityError:
            # The unique constraint on (case_id, question_key) is the real
            # guard; the read above is an optimisation, not a lock.
            session.rollback()
    return {"case_id": case_id, "created": created,
            "total": len(QUESTIONS), "already_present": len(existing)}


def _evidence_for_domain(session, case_id: str, domain_no: int) -> dict | None:
    """The disposition and stored evidence for one input domain, or None.

    Only an EVIDENCED_PUBLIC or DERIVED_PUBLIC row is offered as prefill
    material. A BENCHMARK_PRIOR is the model's own default, not something
    learned about this client, and feeding it back as a suggested answer
    would invite the client to confirm the system's own assumption - which
    would then read as client-confirmed data. That is a circularity worth
    refusing outright.
    """
    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == domain_no)).first()
    if row is None or row.disposition not in ("EVIDENCED_PUBLIC", "DERIVED_PUBLIC"):
        return None
    return {"disposition": row.disposition, "evidence": row.evidence}


def deterministic_prefill(evidence: dict | None) -> tuple[str | None, str]:
    """The non-LLM prefill path. Proposes nothing it cannot source.

    It does not attempt to *read* the evidence - extracting "122 sites" from a
    stored page fragment is exactly the language task the LIVE path is for.
    What it does is surface what was found and say plainly that a person needs
    to read it. A rule that guessed a value from a text fragment would be a
    worse language model, not a deterministic alternative to one.
    """
    if not evidence or not evidence.get("evidence"):
        return None, ("No public evidence is recorded for the input domain this "
                      "question informs, so no answer is suggested.")
    sources = (evidence["evidence"] or {}).get("sources") or []
    if not sources:
        return None, (f"The domain is disposed {evidence['disposition']} but no "
                      f"source fragments are stored, so no answer is suggested.")
    urls = ", ".join(s.get("url", "?") for s in sources[:3])
    return None, (f"{len(sources)} public source(s) recorded for this domain "
                  f"({urls}) - review them directly; this build does not "
                  f"extract a value from them without a model.")


def prefill(session, *, case_id: str, mode: str = "LIVE",
            provider: str = "anthropic", overwrite: bool = False,
            idempotency_key: str | None = None) -> dict:
    """Runs LLM-02 prefill across the case's questionnaire.

    mode is an explicit choice, never inferred and never switched
    automatically on a LIVE failure - the same guarantee gateway.py enforces
    and Tranche 2 restated. DETERMINISTIC_ONLY here does not create an agent
    run: LLM-02 is registered LIVE-only, so requesting DETERMINISTIC_ONLY
    through the gateway would be correctly refused. It runs
    deterministic_prefill() directly instead, and labels the result
    DETERMINISTIC_PROPOSED so nothing reads as model output that wasn't.

    Never overwrites an answered item under any circumstances, overwrite or
    not: a client's answer is not this function's to replace.
    """
    if mode not in ("LIVE", "DETERMINISTIC_ONLY"):
        raise ValueError(f"prefill() supports LIVE or DETERMINISTIC_ONLY, not {mode!r}")
    if mode == "LIVE" and "LLM-02" not in registry.AGENTS:
        raise RuntimeError("LLM-02 is not registered - registry.py is out of sync")

    items = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id).order_by(
        db.questionnaire_item.c.domain_no)).all()
    if not items:
        raise LookupError(
            f"no questionnaire for case {case_id}; create it first")

    # Fresh per invocation unless supplied - see research.py's note.
    request_scope = idempotency_key or str(uuid.uuid4())
    results, failed = [], 0
    for item in items:
        if item.answer_value:
            results.append({"question_key": item.question_key,
                            "skipped": "already answered by the client"})
            continue
        if item.prefill_value is not None and not overwrite:
            results.append({"question_key": item.question_key,
                            "skipped": "already prefilled; pass overwrite=true"})
            continue

        evidence = _evidence_for_domain(session, case_id, item.domain_no)

        if mode == "DETERMINISTIC_ONLY":
            value, basis = deterministic_prefill(evidence)
            label, run_id = "DETERMINISTIC_PROPOSED", None
        else:
            run_id = None
            try:
                run_id = gateway.create_agent_run(
                    session, agent_id="LLM-02", mode="LIVE", case_id=case_id,
                    idempotency_key=f"prefill:{request_scope}:{item.question_key}")
                call = gateway.execute(
                    session, agent_run_id=run_id, provider=provider,
                    system=_PREFILL_SYSTEM_PROMPT,
                    prompt=_build_prefill_prompt(item, evidence))
                parsed = gateway.parse_json_strict(call["text"])
                if not isinstance(parsed, dict) or "prefill_value" not in parsed:
                    gateway.fail(session, run_id,
                                 "LLM-02 output was valid JSON but not the agreed shape")
                    raise errors.StructuredOutputInvalid(
                        "LLM-02 output was valid JSON but not the agreed shape")
            except (errors.ProviderUnavailable, errors.LivenessProofFailed,
                    errors.StructuredOutputInvalid, errors.ModeNotPermitted) as exc:
                if run_id is not None:
                    gateway.fail(session, run_id, f"{type(exc).__name__}: {exc}")
                failed += 1
                results.append({"question_key": item.question_key,
                                "failed": f"{type(exc).__name__}: {exc}"})
                continue
            value = parsed.get("prefill_value")
            value = None if value is None else str(value)
            basis = str(parsed.get("basis", ""))
            label = "LLM_PROPOSED"
            gateway.succeed(session, run_id, {"prefill_value": value})

        session.execute(update(db.questionnaire_item)
                        .where(db.questionnaire_item.c.item_id == item.item_id)
                        .values(prefill_value=value, prefill_basis=basis,
                                prefill_label=label, prefill_agent_run_id=run_id))
        session.commit()
        results.append({"question_key": item.question_key, "prefill_value": value,
                        "label": label, "had_evidence": evidence is not None})

    return {"case_id": case_id, "mode": mode, "items": len(items),
            "failed": failed, "results": results}


def _build_prefill_prompt(item, evidence: dict | None) -> str:
    domain_name = dict(dispositions.DOMAINS).get(item.domain_no, "unknown domain")
    fenced_q = gateway.fence("question", item.question_text)
    if evidence and evidence.get("evidence"):
        sources = (evidence["evidence"] or {}).get("sources") or []
        body = "\n\n".join(
            f"source: {s.get('url', '?')}\npublisher: {s.get('publisher', '?')}\n"
            f"fragment: {s.get('fragment', '')}" for s in sources[:5])
        fenced_e = gateway.fence("public_evidence", body)
    else:
        fenced_e = gateway.fence("public_evidence",
                                 "(no public evidence recorded for this domain)")
    return (f"Input domain: {domain_name}\n{fenced_q}\n{fenced_e}\n"
            f"Respond with the JSON object only.")


def answer(session, *, case_id: str, question_key: str, answer_value: str,
           answered_by: str) -> dict:
    """Records a client's answer. answered_by is a named person at the client,
    held to the same bar known_facts.py holds asserted_by to - an
    unattributed answer is rejected rather than stored anonymously."""
    if not answer_value or not str(answer_value).strip():
        raise ValueError("answer_value is mandatory; record no answer rather "
                         "than an empty one")
    if not answered_by or not answered_by.strip():
        raise ValueError(
            "answered_by is mandatory; an unattributed client answer is "
            "rejected on the same basis as an unattributed known fact (0.1B)")
    if question_key not in QUESTION_KEYS:
        raise ValueError(f"unknown question_key {question_key!r}")

    row = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id,
        db.questionnaire_item.c.question_key == question_key)).one_or_none()
    if row is None:
        raise LookupError(
            f"no questionnaire item {question_key!r} for case {case_id}")

    session.execute(update(db.questionnaire_item)
                    .where(db.questionnaire_item.c.item_id == row.item_id)
                    .values(answer_value=str(answer_value).strip(),
                            answered_by=answered_by.strip(),
                            answered_at=datetime.now(timezone.utc)))
    session.commit()
    return _load_one(session, row.item_id)


def _load_one(session, item_id: str) -> dict:
    row = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.item_id == item_id)).one()
    return dict(row._mapping)


def load(session, case_id: str) -> dict:
    rows = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id).order_by(
        db.questionnaire_item.c.domain_no)).all()
    items = [dict(r._mapping) for r in rows]
    answered = [i for i in items if i["answer_value"]]
    return {"case_id": case_id, "items": items,
            "answered": len(answered), "total": len(items),
            "complete": bool(items) and len(answered) == len(items)}


# --------------------------------------------------------------- evidence mapping
#
# The half of LLM-02 the first Tranche 3 slice deliberately deferred, and the
# reason it was deferred is now resolved: dispositions.CLIENT_CONFIRMED gives
# a client's own statement a class of its own, between an analyst's unverified
# recollection and independently-checkable public evidence.
#
# Mapping is rule-based, not a model call. Deciding whether a client answer may
# overwrite existing evidence is a governance question, not a language one -
# routing it through an LLM would make an authority decision unauditable for
# no gain. LLM-02's model half remains prefill.

MAPPING_STATES = ("UPGRADED", "CORROBORATION_REQUIRED", "REFUSED_SIMULATED",
                  "ALREADY_CLIENT_CONFIRMED", "NO_DISPOSITION_ROW")

# What a client answer is permitted to overwrite outright. Each of these is
# either an admission of ignorance or a claim weaker than first-party data.
_UPGRADEABLE = ("DECLARED_UNKNOWN", "BENCHMARK_PRIOR", "ANALYST_ASSERTED_PRIOR")

# Independent evidence. A client answer does NOT silently replace these: two
# independent sources disagreeing is information, and resolving it by letting
# whichever arrived last win would discard it.
_INDEPENDENT = ("EVIDENCED_PUBLIC", "DERIVED_PUBLIC")

RESOLUTIONS = ("CLIENT_AGREES_WITH_PUBLIC", "CLIENT_CONTRADICTS_PUBLIC",
               "CLIENT_SUPERSEDES_PUBLIC")


def map_answers(session, *, case_id: str, mapped_by: str) -> dict:
    """Maps answered questionnaire items onto the 0.3A disposition contract.

    Five outcomes, and only one of them writes a disposition automatically:

      UPGRADED                 - the domain held DECLARED_UNKNOWN, a benchmark
                                 prior or an analyst assertion. First-party
                                 client data beats all three, so the domain
                                 becomes CLIENT_CONFIRMED.
      CORROBORATION_REQUIRED   - the domain already holds public evidence. The
                                 disposition is left exactly as it was and the
                                 answer is flagged for a named person to
                                 adjudicate via resolve_mapping(). Letting the
                                 client answer overwrite would discard the
                                 disagreement, which is the most informative
                                 thing here.
      REFUSED_SIMULATED        - the quantity was decided by the seeded draw.
                                 Silently replacing it would break the 0.6A
                                 simulated-share derivation, which is computed
                                 from component quantity origins. Flagged, not
                                 overwritten.
      ALREADY_CLIENT_CONFIRMED - nothing to do.
      NO_DISPOSITION_ROW       - the domain has no disposition at all yet, so
                                 there is nothing to upgrade *from*. Written as
                                 CLIENT_CONFIRMED, same as an upgrade.

    mapped_by is required and named: this changes what the estimate rests on.
    """
    if not mapped_by or not mapped_by.strip():
        raise ValueError(
            "mapped_by is mandatory; mapping client answers onto the "
            "disposition contract changes what the estimate rests on and is "
            "attributed to a named person")

    items = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id).order_by(
        db.questionnaire_item.c.domain_no)).all()
    if not items:
        raise LookupError(f"no questionnaire for case {case_id}")

    now = datetime.now(timezone.utc)
    results, upgraded, flagged = [], 0, 0

    for item in items:
        if not item.answer_value:
            continue

        row = session.execute(select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id,
            db.domain_disposition.c.domain_no == item.domain_no)).first()
        current = row.disposition if row is not None else None

        if current == "CLIENT_CONFIRMED":
            state, note = "ALREADY_CLIENT_CONFIRMED", "no change"
        elif current in _INDEPENDENT:
            state = "CORROBORATION_REQUIRED"
            note = (f"domain {item.domain_no} already holds {current}; the "
                    f"client's answer is recorded but has not replaced it. A "
                    f"named person must adjudicate: agreement, contradiction, "
                    f"or a deliberate supersede.")
            flagged += 1
        elif current == "SIMULATED":
            state = "REFUSED_SIMULATED"
            note = (f"domain {item.domain_no} is SIMULATED - the quantity came "
                    f"from the seeded draw. Replacing it here would change the "
                    f"0.6A simulated share without the simulation being re-run. "
                    f"Re-run the simulation with this value as an input instead.")
            flagged += 1
        else:
            state = "UPGRADED" if current is not None else "NO_DISPOSITION_ROW"
            note = (f"client answer supersedes {current or 'no disposition'}; "
                    f"domain now CLIENT_CONFIRMED")
            _write_client_disposition(session, case_id=case_id, item=item)
            upgraded += 1

        session.execute(update(db.questionnaire_item)
                        .where(db.questionnaire_item.c.item_id == item.item_id)
                        .values(mapping_state=state, mapping_note=note,
                                mapped_at=now))
        session.commit()
        results.append({"question_key": item.question_key,
                        "domain_no": item.domain_no,
                        "previous_disposition": current,
                        "mapping_state": state, "note": note})

    return {"case_id": case_id, "mapped_by": mapped_by.strip(),
            "answers_mapped": len(results), "upgraded": upgraded,
            "requiring_adjudication": flagged, "results": results}


def _write_client_disposition(session, *, case_id: str, item) -> None:
    """Writes or updates one domain's disposition to CLIENT_CONFIRMED.

    The evidence column carries the answer, the question and the named
    respondent - so a CLIENT_CONFIRMED row is traceable to a person who said
    it, exactly as an EVIDENCED_PUBLIC row is traceable to a fetched source.
    A disposition nobody can trace back is the defect this whole bundle keeps
    closing.
    """
    domain_name = dict(dispositions.DOMAINS).get(item.domain_no, "")
    evidence = {"client_answer": item.answer_value,
                "question_key": item.question_key,
                "question_text": item.question_text,
                "answered_by": item.answered_by,
                "answered_at": item.answered_at.isoformat()
                if item.answered_at else None}
    existing = session.execute(
        select(db.domain_disposition.c.id).where(
            db.domain_disposition.c.case_id == case_id,
            db.domain_disposition.c.domain_no == item.domain_no)).first()
    values = {"disposition": "CLIENT_CONFIRMED", "reason": None,
              "agent_run_id": None, "evidence": evidence}
    if existing:
        session.execute(update(db.domain_disposition)
                        .where(db.domain_disposition.c.id == existing.id)
                        .values(**values))
    else:
        session.execute(insert(db.domain_disposition).values(
            id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
            domain_no=item.domain_no, domain_name=domain_name, **values))


def resolve_mapping(session, *, case_id: str, question_key: str,
                    resolution: str, resolved_by: str, note: str = "") -> dict:
    """Adjudicates a CORROBORATION_REQUIRED answer. A named person only.

    CLIENT_AGREES_WITH_PUBLIC  - both sources say the same thing. The public
                                 disposition stands; agreement is recorded but
                                 does not upgrade anything, because two sources
                                 agreeing does not make either more public.
    CLIENT_CONTRADICTS_PUBLIC  - they disagree and the disagreement is real.
                                 The public disposition stands and the conflict
                                 is recorded. Nothing is silently reconciled:
                                 an unresolved contradiction is a finding, and
                                 the stage gate treats it as one.
    CLIENT_SUPERSEDES_PUBLIC   - the named person judges the client correct and
                                 the public source stale or wrong. Only this
                                 rewrites the disposition to CLIENT_CONFIRMED,
                                 and it requires a stated reason: overriding
                                 independently-verifiable evidence with a
                                 self-report needs to be defensible later.
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}, not {resolution!r}")
    if not resolved_by or not resolved_by.strip():
        raise ValueError("resolved_by is mandatory; an unattributed adjudication "
                         "is rejected")
    if resolution == "CLIENT_SUPERSEDES_PUBLIC" and not (note or "").strip():
        raise ValueError(
            "CLIENT_SUPERSEDES_PUBLIC requires a stated reason: it overrides "
            "independently-verifiable public evidence with a client's "
            "self-report, and that has to be defensible after the fact")

    item = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id,
        db.questionnaire_item.c.question_key == question_key)).one_or_none()
    if item is None:
        raise LookupError(f"no questionnaire item {question_key!r} for case {case_id}")
    if item.mapping_state != "CORROBORATION_REQUIRED":
        raise ValueError(
            f"item {question_key!r} is {item.mapping_state!r}, not "
            f"CORROBORATION_REQUIRED - there is nothing to adjudicate")

    if resolution == "CLIENT_SUPERSEDES_PUBLIC":
        _write_client_disposition(session, case_id=case_id, item=item)

    session.execute(update(db.questionnaire_item)
                    .where(db.questionnaire_item.c.item_id == item.item_id)
                    .values(mapping_resolution=resolution,
                            mapping_resolved_by=resolved_by.strip(),
                            mapping_resolved_at=datetime.now(timezone.utc),
                            mapping_note=(note or "").strip() or item.mapping_note))
    session.commit()
    return _load_one(session, item.item_id)


def unresolved_conflicts(session, case_id: str) -> list[dict]:
    """Answers that met independent evidence and have not been adjudicated,
    plus adjudicated contradictions still standing. The stage gate reads this."""
    rows = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id,
        db.questionnaire_item.c.mapping_state == "CORROBORATION_REQUIRED")).all()
    return [dict(r._mapping) for r in rows
            if r.mapping_resolution in (None, "CLIENT_CONTRADICTS_PUBLIC")]
