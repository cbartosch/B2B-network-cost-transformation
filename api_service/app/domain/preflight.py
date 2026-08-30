"""Pre-flight readiness check (spec 0.1C).

Every knowable constraint is moved in front of the run. A BLOCK condition
prevents execution; the report is persisted so what the team knew before
executing is auditable afterwards.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from .. import config, db
from ..llm import gateway
from . import entity_resolution

BLOCK, WARN, PASS = "BLOCK", "WARN", "PASS"

MANDATORY_FIELDS = [
    "subject_entity_legal_name", "entity_identifier", "country_of_domicile",
    "group_perimeter", "in_scope_countries", "in_scope_cost_layers",
    "in_scope_service_families", "base_currency", "price_year", "fx_convention",
    "analysis_horizon_years", "discount_rate_set_id", "engagement_purpose",
    "client_contact_status", "baseline_reference_period",
]


def _c(item, state, detail):
    return {"item": item, "state": state, "detail": detail}


def run(session, *, case_id: str, mode: str = "LIVE") -> dict:
    row = session.execute(select(db.case).where(db.case.c.case_id == case_id)).first()
    if row is None:
        raise LookupError(f"case {case_id!r} not found")
    conditions = []

    # 1. Entity resolution
    if entity_resolution.is_confirmed(session, case_id):
        conditions.append(_c("Entity resolution", PASS,
                             f"{row.subject_entity_legal_name} confirmed by "
                             f"{row.entity_confirmed_by}, perimeter v{row.perimeter_version}"))
    else:
        conditions.append(_c("Entity resolution", BLOCK,
                             "subject entity not confirmed by a named user"))

    # 2. Mandatory intake
    # in_scope_countries can legitimately be an empty list: a REGION or
    # GLOBAL selection (domain/scope.py) that matches no approved pricing
    # prior resolves to [], which is a real outcome of a deliberate choice,
    # not an unset field. The blanket falsy check below can't tell those
    # apart - `not []` and `not None` are both True - so it's checked
    # separately and given its own message when in_scope_region says a
    # geography selector actually ran.
    via_selector = bool(row.in_scope_region)
    check_fields = [f for f in MANDATORY_FIELDS if not (via_selector and f == "in_scope_countries")]
    missing = [f for f in check_fields if not getattr(row, f, None)]

    geography_empty = via_selector and not row.in_scope_countries
    if missing or geography_empty:
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if geography_empty:
            detail.append(
                f"'{row.in_scope_region}' resolved to zero in-scope countries - "
                f"no approved pricing benchmark matches this selection")
        conditions.append(_c("Mandatory intake", BLOCK, "; ".join(detail)))
    else:
        conditions.append(_c("Mandatory intake", PASS, "all fields populated"))

    # 3. Provider availability - BLOCK for LIVE, and never auto-downgraded
    avail = gateway.available_providers()
    live_ok = any(avail.values())
    if mode == "LIVE" and not live_ok:
        conditions.append(_c("Provider availability", BLOCK,
                             "no approved provider adapter is configured; a LIVE run "
                             "fails closed rather than downgrading"))
    elif mode == "LIVE" and config.PREFLIGHT_PROBE_LIVE:
        conditions.append(_c("Provider availability", PASS,
                             f"configured: {[k for k, v in avail.items() if v]}"))
    else:
        conditions.append(_c("Provider availability", PASS if live_ok else WARN,
                             f"configured: {[k for k, v in avail.items() if v] or 'none'}"))

    # 4. Prior coverage - WARN here, refused at publication (0.3C)
    countries = row.in_scope_countries or []
    priced = _priced_countries(session, countries)
    uncovered = sorted(set(countries) - priced)
    conditions.append(_c("Prior coverage", PASS, f"priors present for all {len(countries)} countries")
                      if not uncovered else
                      _c("Prior coverage", WARN,
                         f"no approved reference prior for: {', '.join(uncovered)}. "
                         f"Publication will be PARTIAL or refused under 0.3C."))

    # 5. Benchmark releases - absence is expected at launch (5.1)
    conditions.append(_c("Benchmark release availability", WARN,
                         "benchmark vault empty; V0 runs on reference priors, which is "
                         "expected before any engagement reaches V2"))

    # 6/7. Known-fact contradictions and rights
    facts = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_id)).all()
    contradicted = [f for f in facts if f.corroboration_state == "CONTRADICTED"]
    conditions.append(_c("Known-fact contradictions", PASS, "none outstanding") if not contradicted
                      else _c("Known-fact contradictions", WARN,
                              f"{len(contradicted)} contradicted; BLOCK before publication"))

    uncleared = [f for f in facts if f.basis == "PRIOR_ENGAGEMENT" and not f.rights_cleared]
    conditions.append(_c("Prior-engagement rights", PASS, "cleared or not applicable")
                      if not uncleared else
                      _c("Prior-engagement rights", BLOCK,
                         f"{len(uncleared)} PRIOR_ENGAGEMENT fact(s) awaiting a rights check; "
                         f"a fact carrying another client's confidential information may not "
                         f"influence an estimate"))

    # 8. Financial policy
    fin_ok = all([row.discount_rate_set_id, row.analysis_horizon_years,
                  row.base_currency, row.price_year])
    conditions.append(_c("Financial policy", PASS if fin_ok else BLOCK,
                         "resolved" if fin_ok else "discount rate / horizon / currency unresolved"))

    blocked = any(c["state"] == BLOCK for c in conditions)
    report_id = str(uuid.uuid4())
    session.execute(insert(db.preflight_report).values(
        report_id=report_id, case_id=case_id, conditions=conditions, blocked=blocked))
    session.commit()
    return {"report_id": report_id, "blocked": blocked, "conditions": conditions,
            "blocks": [c for c in conditions if c["state"] == BLOCK],
            "warns": [c for c in conditions if c["state"] == WARN]}


def _priced_countries(session, countries) -> set:
    if not countries:
        return set()
    rows = session.execute(select(db.unit_cost_prior.c.country).where(
        db.unit_cost_prior.c.country.in_(countries),
        db.unit_cost_prior.c.approved.is_(True))).all()
    return {r.country for r in rows}


def latest(session, case_id: str):
    """Read-only. GET must not create a report - an earlier revision inserted on
    every read, which silently invalidated a prior acknowledgement."""
    return session.execute(
        select(db.preflight_report)
        .where(db.preflight_report.c.case_id == case_id)
        .order_by(db.preflight_report.c.created_at.desc()).limit(1)).first()


def acknowledge(session, *, report_id: str, acknowledged_by: str) -> dict:
    session.execute(update(db.preflight_report)
                    .where(db.preflight_report.c.report_id == report_id)
                    .values(acknowledged_by=acknowledged_by,
                            acknowledged_at=datetime.now(timezone.utc)))
    session.commit()
    return {"report_id": report_id, "acknowledged_by": acknowledged_by}


def assert_clear_to_run(session, case_id: str) -> None:
    """Called before any V0 execution. A run may not begin while a BLOCK is open."""
    report = latest(session, case_id)
    if report is None:
        raise PermissionError("no pre-flight report; run the readiness check first (0.1C)")
    if report.blocked:
        blocks = [c["item"] for c in report.conditions if c["state"] == BLOCK]
        raise PermissionError(f"pre-flight BLOCK conditions open: {', '.join(blocks)}")
    if not report.acknowledged_by:
        raise PermissionError("pre-flight report has not been acknowledged by a named user")
