"""Stage model and stage-readiness gate (Tranche 3, first slice).

The bundle had no concept of an engagement stage at all before this, despite
the analytical model depending on one: confidence.STAGE_CEILINGS is keyed by
stage, reference.lever.earliest_supported_stage gates when a lever's evidence
becomes admissible, and preflight.py's own text says "expected before any
engagement reaches V2". Every one of those read V0 because V0 was hardcoded
at the call site - the only value the system could produce.

What this module does and deliberately does not do:

**Stage is advanced by a named person, never inferred.** A questionnaire
existing, or being fully answered, is not the same claim as "this engagement
is at V1". Only a person can make the second one, and the record says who.
Same discipline as entity_confirmed_by and preflight acknowledged_by.

**The gate refuses; it does not degrade.** A BLOCK condition means advance()
raises. There is no "advance anyway with a warning" path, because the whole
point of a gate that can be overridden silently is that it isn't one. A WARN
is advisory and does not block.

**This slice implements V0 -> V1 only.** V1 -> V2 requires contract and
invoice ingestion, which requires object storage, which does not exist in
this build. TARGET_STAGES is the honest list of what can actually be
requested, not the full V0-V5 ladder the spec describes: advertising a V2
target with no ingestion behind it would be exactly the false-capability
claim registry.py's own docstring was written about.

**Stage does not yet feed the confidence engine.** confidence.py's
STAGE_CEILINGS has one entry, V0, seeded with three values. A case at V1
would need stage_ceiling_V1_* rows in reference.threshold before
confidence.compute could be called with stage="V1", and those are governed
figures nobody has approved - policy.py holds no defaults by design, so
inventing them here would be the exact defect that module exists to prevent.
Advancing to V1 therefore changes what the case *is*, and is recorded and
reported, but does not yet change any published number. That is a real
limitation, not an oversight, and it is named in the README's known gaps.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from .. import db
from . import dispositions, questionnaire

log = logging.getLogger("workbench.stage")

BLOCK, WARN, PASS = "BLOCK", "WARN", "PASS"

# The full ladder the analytical model refers to. Declared so the vocabulary
# is in one place; not all of it is reachable - see TARGET_STAGES.
STAGES = ("V0", "V1", "V2", "V3", "V4", "V5")

# Transitions this build can actually gate. V1 -> V2 needs document ingestion
# and object storage, neither of which exists here.
TARGET_STAGES = ("V1",)


def _c(item, state, detail):
    return {"item": item, "state": state, "detail": detail}


def current_stage(case_row) -> str:
    """NULL means V0. Migration v13 adds the column to existing rows without
    backfilling the default, so a case created before this build reads NULL -
    and a pre-stage-model case is by definition at V0, not at 'unknown'."""
    return getattr(case_row, "stage", None) or "V0"


def _predecessor(target_stage: str) -> str:
    """Guarded rather than a bare index: STAGES[-1] for 'V0' would silently
    return 'V5' and read as a plausible answer. Unreachable today because both
    callers validate against TARGET_STAGES first, but the failure mode is bad
    enough to close now rather than rely on that staying true."""
    if target_stage == STAGES[0]:
        raise ValueError(f"{STAGES[0]} has no predecessor stage")
    return STAGES[STAGES.index(target_stage) - 1]


def assess(session, *, case_id: str, target_stage: str = "V1") -> dict:
    """Evaluates readiness to advance, persists the report, returns it.

    Raises LookupError for an unknown case and ValueError for a target stage
    this build cannot gate.
    """
    if target_stage not in TARGET_STAGES:
        raise ValueError(
            f"this build can only assess readiness for {TARGET_STAGES}, not "
            f"{target_stage!r} - V2 and above need document ingestion, which "
            f"is not implemented")

    case_row = session.execute(
        select(db.case).where(db.case.c.case_id == case_id)).one_or_none()
    if case_row is None:
        raise LookupError(f"no such case: {case_id}")

    conditions = []
    now_at = current_stage(case_row)
    expected_from = _predecessor(target_stage)

    # 1. The case is at the stage immediately below the target. No skipping,
    #    and no re-advancing a case that is already there or beyond.
    if now_at == expected_from:
        conditions.append(_c("Current stage", PASS,
                             f"case is at {now_at}; target {target_stage}"))
    else:
        conditions.append(_c("Current stage", BLOCK,
                             f"case is at {now_at}; {target_stage} may only be "
                             f"reached from {expected_from}"))

    # 2. A published V0 estimate exists. V1 refines a baseline; there has to
    #    be one to refine.
    snap = session.execute(
        select(db.estimate_snapshot.c.estimate_snapshot_id,
               db.estimate_snapshot.c.v0_status)
        .where(db.estimate_snapshot.c.case_id == case_id)
        .order_by(db.estimate_snapshot.c.created_at.desc()).limit(1)).first()
    if snap is None:
        conditions.append(_c("V0 estimate", BLOCK,
                             "no estimate snapshot; V1 refines a V0 baseline and "
                             "there is none to refine"))
    elif snap.v0_status == "REFUSED":
        conditions.append(_c("V0 estimate", BLOCK,
                             "the latest V0 estimate was REFUSED by the coverage "
                             "gate; advancing would build on a baseline 0.3C "
                             "declined to publish"))
    else:
        conditions.append(_c("V0 estimate", PASS,
                             f"latest snapshot {snap.estimate_snapshot_id[:8]} "
                             f"is {snap.v0_status}"))

    # 3. Every one of the 24 input domains carries a disposition. This is the
    #    same contract validate() enforces at publication, re-checked here
    #    because a case can reach V1 by a path that never published.
    disp = [dict(r._mapping) for r in session.execute(
        select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id)).all()]
    blockers = dispositions.validate(disp) if disp else ["no dispositions recorded"]
    conditions.append(_c("Domain dispositions", PASS,
                         f"all {len(dispositions.DOMAINS)} domains disposed")
                      if not blockers else
                      _c("Domain dispositions", BLOCK,
                         f"{len(blockers)} unresolved: {'; '.join(blockers[:3])}"
                         + (" ..." if len(blockers) > 3 else "")))

    # 4. A questionnaire exists and has been answered. The threshold is
    #    deliberately "every item answered" rather than a governed percentage:
    #    a partial-response rule would be a material threshold, and 18.1 says
    #    those live in reference.threshold with an approver, not in this file.
    #    An all-or-nothing rule needs no governed number to be honest.
    items = session.execute(select(db.questionnaire_item).where(
        db.questionnaire_item.c.case_id == case_id)).all()
    if not items:
        conditions.append(_c("V1 questionnaire", BLOCK,
                             "no questionnaire has been created for this case"))
    else:
        unanswered = [i for i in items if not i.answer_value]
        if unanswered:
            conditions.append(_c("V1 questionnaire", BLOCK,
                                 f"{len(unanswered)} of {len(items)} items "
                                 f"unanswered"))
        else:
            unattributed = [i for i in items if not i.answered_by]
            conditions.append(_c("V1 questionnaire", PASS,
                                 f"all {len(items)} items answered")
                              if not unattributed else
                              _c("V1 questionnaire", BLOCK,
                                 f"{len(unattributed)} answer(s) with no named "
                                 f"respondent; an unattributed client answer is "
                                 f"rejected on the same basis as an unattributed "
                                 f"known fact (0.1B)"))

    # 4b. Client answers that met independent public evidence and have not
    #     been adjudicated - or were adjudicated as a real contradiction and
    #     still stand. Advancing with either open would mean carrying an
    #     unreconciled disagreement between two independent sources into the
    #     stage that exists to refine the baseline.
    conflicts = questionnaire.unresolved_conflicts(session, case_id)
    conditions.append(_c("Client/public reconciliation", PASS,
                         "no unadjudicated or contradicted client answers")
                      if not conflicts else
                      _c("Client/public reconciliation", BLOCK,
                         f"{len(conflicts)} client answer(s) disagree with, or "
                         f"have not been adjudicated against, existing public "
                         f"evidence: "
                         f"{', '.join(c['question_key'] for c in conflicts[:3])}"
                         + (" ..." if len(conflicts) > 3 else "")))

    # 4c. Answers recorded but never mapped onto the disposition contract.
    #     An answer that never reached a disposition changed nothing, which is
    #     not what "the questionnaire is complete" implies.
    answered = [i for i in items if i.answer_value]
    unmapped = [i for i in answered if not i.mapping_state]
    conditions.append(_c("Answer mapping", PASS,
                         f"all {len(answered)} answer(s) mapped onto their input "
                         f"domains" if answered else "no answers to map yet")
                      if not unmapped else
                      _c("Answer mapping", BLOCK,
                         f"{len(unmapped)} answered item(s) never mapped; run "
                         f"questionnaire:map so the answers actually reach the "
                         f"disposition contract"))

    # 5. Known-fact contradictions. A WARN at 0.1C pre-flight; a BLOCK here,
    #    because carrying an unresolved contradiction into a stage that exists
    #    to refine the baseline defeats the point of advancing.
    facts = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_id)).all()
    contradicted = [f for f in facts if f.corroboration_state == "CONTRADICTED"]
    conditions.append(_c("Known-fact contradictions", PASS, "none outstanding")
                      if not contradicted else
                      _c("Known-fact contradictions", BLOCK,
                         f"{len(contradicted)} contradicted fact(s) unresolved"))

    # 6. Advisory: what V1 cannot yet change. Reported so nobody reads an
    #    advance as more than it is.
    conditions.append(_c("Stage-aware confidence", WARN,
                         "confidence ceilings are seeded for V0 only; a case at "
                         "V1 is recorded as V1 but published figures are "
                         "unchanged until stage_ceiling_V1_* is governed"))

    blocked = any(c["state"] == BLOCK for c in conditions)
    report_id = str(uuid.uuid4())
    session.execute(insert(db.stage_readiness_report).values(
        report_id=report_id, case_id=case_id, target_stage=target_stage,
        conditions=conditions, blocked=blocked))
    session.commit()
    return {"report_id": report_id, "case_id": case_id,
            "current_stage": now_at, "target_stage": target_stage,
            "blocked": blocked, "conditions": conditions,
            "blocks": [c for c in conditions if c["state"] == BLOCK],
            "warns": [c for c in conditions if c["state"] == WARN]}


def latest(session, case_id: str, target_stage: str = "V1"):
    """Read-only. Mirrors preflight.latest's own comment: a GET must not
    create a report, because that would silently invalidate an existing
    acknowledgement."""
    return session.execute(
        select(db.stage_readiness_report)
        .where(db.stage_readiness_report.c.case_id == case_id,
               db.stage_readiness_report.c.target_stage == target_stage)
        .order_by(db.stage_readiness_report.c.created_at.desc()).limit(1)).first()


def acknowledge(session, *, report_id: str, acknowledged_by: str) -> dict:
    if not acknowledged_by or not acknowledged_by.strip():
        raise ValueError(
            "acknowledged_by is mandatory; an unattributed acknowledgement is "
            "rejected, same bar as known_facts.asserted_by")
    row = session.execute(select(db.stage_readiness_report).where(
        db.stage_readiness_report.c.report_id == report_id)).one_or_none()
    if row is None:
        raise LookupError(f"no such stage-readiness report: {report_id}")
    session.execute(update(db.stage_readiness_report)
                    .where(db.stage_readiness_report.c.report_id == report_id)
                    .values(acknowledged_by=acknowledged_by.strip(),
                            acknowledged_at=datetime.now(timezone.utc)))
    session.commit()
    return {"report_id": report_id, "acknowledged_by": acknowledged_by.strip()}


def advance(session, *, case_id: str, target_stage: str = "V1",
            advanced_by: str) -> dict:
    """Advances the case, or refuses.

    Refuses (PermissionError) when there is no readiness report, when the
    latest one is stale relative to the case's current stage, when it carries
    an open BLOCK, or when it has not been acknowledged by a named person.
    There is deliberately no force/override parameter.
    """
    if not advanced_by or not advanced_by.strip():
        raise ValueError("advanced_by is mandatory; a stage advance is attributed "
                         "to a named person, never a role or a team")
    if target_stage not in TARGET_STAGES:
        raise ValueError(
            f"this build can only advance to {TARGET_STAGES}, not {target_stage!r}")

    case_row = session.execute(
        select(db.case).where(db.case.c.case_id == case_id)).one_or_none()
    if case_row is None:
        raise LookupError(f"no such case: {case_id}")

    report = latest(session, case_id, target_stage)
    if report is None:
        raise PermissionError(
            f"no stage-readiness report for {target_stage}; assess first")
    if report.blocked:
        blocks = [c["item"] for c in report.conditions if c["state"] == BLOCK]
        raise PermissionError(
            f"stage-readiness BLOCK conditions open: {', '.join(blocks)}")
    if not report.acknowledged_by:
        raise PermissionError(
            "the stage-readiness report has not been acknowledged by a named user")

    # The report was assessed against a stage the case may since have left.
    # Re-checking here rather than trusting the report closes the window
    # between assess() and advance().
    now_at = current_stage(case_row)
    if now_at != _predecessor(target_stage):
        raise PermissionError(
            f"case is at {now_at}, not {_predecessor(target_stage)}; the "
            f"readiness report is stale - re-assess")

    session.execute(update(db.case).where(db.case.c.case_id == case_id)
                    .values(stage=target_stage,
                            stage_advanced_by=advanced_by.strip(),
                            stage_advanced_at=datetime.now(timezone.utc)))
    session.commit()
    log.info("case %s advanced %s -> %s by %s", case_id, now_at, target_stage,
             advanced_by.strip())
    return {"case_id": case_id, "stage": target_stage,
            "advanced_from": now_at, "advanced_by": advanced_by.strip(),
            "report_id": report.report_id}
