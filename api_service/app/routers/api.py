"""FastAPI control plane. Streamlit reaches the system only through here."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Body, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, text, update

from .. import config, db, jobs, migrations
from ..domain import (benchmark_ingest, confidence, coverage, dispositions,
                      entity_resolution,
                      estimate, known_facts, policy, preflight, promotion, questionnaire,
                      reachability, reconciliation, research, savings_advisory,
                      scope, simulation, stage)
from ..domain.money import D, Range
from ..llm import errors, gateway, registry

router = APIRouter()


def S():
    return db.SessionLocal()


def _thresholds(s, set_name):
    rows = s.execute(select(db.threshold).where(db.threshold.c.set_name == set_name)).all()
    return {r.key: str(r.value) for r in rows}


def _one_or_404(session, table, column, value, what: str):
    """Resolve a caller-supplied identifier, or 404.

    SQLAlchemy's .one() raises NoResultFound on a miss, which FastAPI renders as
    a 500 - telling a caller the server is broken when their identifier is
    simply wrong. Nine call sites did this; one helper removes the class.
    """
    row = session.execute(select(table).where(column == value)).first()
    if row is None:
        raise HTTPException(404, f"{what} {value!r} not found")
    return row


def _policies(s):
    """Load and validate the governed policy sets.

    A missing or inconsistent value is a 503, not a fallback: the domain layer
    holds no defaults, so an unusable policy means the model cannot be run
    rather than run on constants nobody approved.
    """
    try:
        return (policy.ConfidencePolicy.from_rows(_thresholds(s, "confidence_policy")),
                policy.CoveragePolicy.from_rows(_thresholds(s, "v0_coverage_threshold_set")),
                policy.KnownFactPolicy.from_rows(_thresholds(s, "known_fact_policy")))
    except (policy.PolicyIncomplete, policy.PolicyInvalid) as exc:
        raise HTTPException(503, {"error": "governed policy unusable", "detail": str(exc)})


def _reconciliation_policy(s):
    try:
        return policy.ReconciliationPolicy.from_rows(
            _thresholds(s, "provider_reconciliation_tier"))
    except (policy.PolicyIncomplete, policy.PolicyInvalid) as exc:
        raise HTTPException(503, {"error": "governed reconciliation policy unusable",
                                  "detail": str(exc)})


def _research_policy(s):
    """Separate from _policies(): two existing call sites unpack that as a
    3-tuple, and research is not required for every route that needs the
    other three."""
    try:
        # research_budget_profile, not research_policy: the latter was a
        # duplicate set added in Tranche 1 whose wall-clock value was invented
        # while an approved one already existed here.
        return policy.ResearchPolicy.from_rows(
            _thresholds(s, "research_budget_profile"))
    except (policy.PolicyIncomplete, policy.PolicyInvalid) as exc:
        raise HTTPException(503, {"error": "governed research policy unusable",
                                  "detail": str(exc)})


def _recommendation_policy(s):
    try:
        return policy.RecommendationPolicy.from_rows(_thresholds(s, "recommendation_policy"))
    except (policy.PolicyIncomplete, policy.PolicyInvalid) as exc:
        raise HTTPException(503, {"error": "governed recommendation policy unusable",
                                  "detail": str(exc)})


def _open_incidents() -> int:
    try:
        with S() as s:
            return len(s.execute(select(db.integrity_incident.c.incident_id)
                                 .where(db.integrity_incident.c.resolved_at.is_(None))
                                 ).all())
    except Exception:                                # noqa: BLE001
        return -1


def _pin_warnings():
    """Everything worth telling an operator about pinning, in one list.

    Two sources, and the configuration one must not be lost when the database
    lookup fails - a missing library is exactly the condition under which other
    things are also likely to be wrong.
    """
    from ..llm.providers import _transport
    out = []

    status_ = _transport.pin_status()
    for message in status_.get("warnings") or []:
        out.append({"scope": "configuration", "warn": True, "message": message})
    if status_.get("refused"):
        out.append({"scope": "configuration", "warn": True,
                    "message": status_["refused"]})

    try:
        with S() as s:
            rows = s.execute(select(db.llm_run.c.provider,
                                    db.llm_run.c.tls_cert_not_after)
                             .where(db.llm_run.c.tls_cert_not_after.isnot(None))).all()
        latest: dict = {}
        for r in rows:
            if latest.get(r.provider) is None or r.tls_cert_not_after > latest[r.provider]:
                latest[r.provider] = r.tls_cert_not_after
        for provider, not_after in latest.items():
            w = _transport.expiry_warning(not_after)
            if w and w.get("warn"):
                out.append({"scope": "expiry", "provider": provider, **w})
    except Exception:                                # noqa: BLE001
        out.append({"scope": "expiry", "warn": True,
                    "message": "certificate expiry could not be read"})
    return out


def _policy_health():
    try:
        with S() as s:
            confidence_policy, coverage_policy, fact_policy = _policies(s)
        return {"usable": True, "sets": [confidence_policy.set_name,
                                         coverage_policy.set_name]}
    except HTTPException as exc:
        return {"usable": False, "detail": exc.detail}
    except Exception as exc:                         # noqa: BLE001
        return {"usable": False, "detail": str(exc)}


# --------------------------------------------------------------- health / meta
_DEEP_CACHE: dict = {"at": None, "value": None}


def _deep_health():
    """Schema, policy, pin and incident checks.

    Cached briefly. The container healthcheck polls every 10 seconds, and
    running a schema query plus two full policy validations on every poll is a
    validation pass every ten seconds forever for no new information.
    """
    now = datetime.now(timezone.utc)
    cached_at = _DEEP_CACHE["at"]
    if cached_at and (now - cached_at).total_seconds() < config.HEALTH_DEEP_TTL_SECONDS:
        return {**_DEEP_CACHE["value"], "cached": True}
    value = {"schema": migrations.status(), "policy": _policy_health(),
             "tls_pin_warnings": _pin_warnings(),
             "open_integrity_incidents": _open_incidents()}
    # Only a clean result is cached. Caching a failure would keep reporting it
    # after it was fixed, and - worse - a stale success is the shape that let a
    # dead database look healthy.
    healthy = (value["policy"].get("usable")
               and value["schema"].get("up_to_date")
               and value["open_integrity_incidents"] in (0,))
    if healthy:
        _DEEP_CACHE.update(at=now, value=value)
    else:
        _DEEP_CACHE.update(at=None, value=None)
    return {**value, "cached": False}


@router.get("/v1/ready")
def ready(response: Response):
    """Readiness: can this instance serve a request?

    Three questions were being asked of one endpoint, and answering them
    together meant the cheap answer displaced the useful one. Making /v1/health
    shallow removed its database round-trip - and the container healthcheck
    still polled it, so an API with an unreachable database reported healthy and
    `ui depends_on api: service_healthy` would start the interface against it.

      /v1/health              liveness   - is the process up? No dependencies,
                                           because restarting will not fix a
                                           database outage.
      /v1/ready               readiness  - can it serve? One cheap round-trip,
                                           never cached, because a cached
                                           readiness answer is not one.
      /v1/health?deep=true    diagnostics - schema, policy, pins, incidents.
                                           Cached, and for humans.

    The container healthcheck and depends_on use this one.
    """
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:                     # noqa: BLE001
        response.status_code = 503
        return {"ready": False, "reason": "database unreachable",
                "detail": str(exc)[:200]}
    return {"ready": True, "environment": config.environment()}


@router.get("/v1/health")
def health(deep: bool = False):
    from .._version import BUILD
    return {"status": "ok", "environment": config.environment(),
            "build": BUILD,
            "providers": gateway.available_providers(),
            "provider_reconciliation_tiers": gateway.provider_tiers(),
            "transport": gateway.transport_status(),

            "auth_required": bool(config.API_TOKEN),
            "auth_header": config.AUTH_HEADER,
            "simulation": {
                "workers": {"max": config.SIM_WORKERS,
                            "in_flight": jobs.in_flight(),
                            "enforcement": "exact, per process",
                            "guards": "worker threads"},
                "backlog": {"max": config.SIM_QUEUE_MAX,
                            "enforcement": "advisory, not atomic across replicas",
                            "guards": "how much new work is accepted"}},
            "calculation_version": config.CALCULATION_VERSION,
            "simulation_model_version": config.SIMULATION_MODEL_VERSION,
            **(_deep_health() if deep else {})}


@router.get("/v1/agents")
def agents():
    return {"agents": registry.AGENTS,
            "declared_modes": list(registry.DECLARED_MODES),
            "implemented_modes": list(registry.IMPLEMENTED_MODES),
            "provider_reconciliation_tiers": gateway.provider_tiers(),
            "environment": config.environment()}


# --------------------------------------------------------------- 0.1A intake
# --- request models -------------------------------------------------------
# Defined together and before any route. Five of these were introduced anchored
# to a model near the reconciliation endpoint, so they landed 570 lines after
# the routes annotating them - a NameError at import, which is what the API
# container exited on the first time it ran.
# --- validation models for routes that previously took a raw body ----------
# Body(...) gives a KeyError and a 500 on a malformed payload; a model gives a
# 422 naming the field. Six routes took raw bodies, one of which indexed a
# caller-supplied list directly.
class ClearRightsIn(BaseModel):
    cleared_by: str = Field(min_length=1, max_length=120)


class ResolveConflictIn(BaseModel):
    resolution: str = "SCOPE_IS_CORRECT"
    reason: str = Field(min_length=1, max_length=2000)
    resolved_by: str = Field(min_length=1, max_length=120)


class CorroborateIn(BaseModel):
    provider: str = Field(default="anthropic", pattern="^(anthropic|openai)$")
    mode: str = Field(default="LIVE", pattern="^(LIVE|MOCK|REPLAY|DETERMINISTIC_ONLY)$")


class PreflightRunIn(BaseModel):
    mode: str = Field(default="LIVE", pattern="^(LIVE|MOCK|REPLAY|DETERMINISTIC_ONLY)$")


class PreflightAckIn(BaseModel):
    report_id: str = Field(min_length=1, max_length=36)
    acknowledged_by: str = Field(min_length=1, max_length=120)


class DispositionIn(BaseModel):
    domain_no: int = Field(ge=1, le=24)
    domain_name: str = ""
    disposition: str
    reason: str | None = None


class CaseIn(BaseModel):
    created_by: str
    subject_entity_legal_name: str | None = None
    entity_identifier: str | None = None
    country_of_domicile: str | None = None
    group_perimeter: str | None = None
    in_scope_countries: list[str] = []
    in_scope_region: str | None = None
    in_scope_cost_layers: list[str] = []
    in_scope_service_families: list[str] = []
    base_currency: str = "USD"
    price_year: int = 2026
    fx_convention: str = "BUDGET"
    analysis_horizon_years: int = 5
    discount_rate_set_id: str = "DRS-2026-USD"
    engagement_purpose: str = "PROPOSAL_QUALIFICATION"
    client_contact_status: str = "NO_CONTACT"
    baseline_reference_period: str = "FY2026"


@router.post("/v1/outside-in/cases")
def create_case(payload: CaseIn):
    cid = str(uuid.uuid4())
    with S() as s:
        s.execute(insert(db.case).values(case_id=cid, **payload.model_dump()))
        s.commit()
    return {"case_id": cid}


@router.get("/v1/outside-in/cases")
def list_cases():
    with S() as s:
        rows = s.execute(select(db.case).order_by(db.case.c.created_at.desc())).all()
        return {"cases": [dict(r._mapping) for r in rows]}


@router.get("/v1/outside-in/cases/{case_id}")
def get_case(case_id: str):
    with S() as s:
        row = s.execute(select(db.case).where(db.case.c.case_id == case_id)).first()
        if not row:
            raise HTTPException(404, "case not found")
        return dict(row._mapping)


class CaseUpdate(BaseModel):
    """Mandatory intake block, partial update.

    Every field optional so a save only touches what the analyst actually
    edited. `scope_mode` drives how `in_scope_countries` gets populated:
    COUNTRIES uses `in_scope_countries` as typed, REGION and GLOBAL resolve
    server-side (domain.scope) so the same literal-country-list contract
    every downstream consumer already relies on keeps holding.
    """
    subject_entity_legal_name: str | None = None
    entity_identifier: str | None = None
    country_of_domicile: str | None = None
    group_perimeter: str | None = None
    scope_mode: str | None = None
    in_scope_countries: list[str] | None = None
    region: str | None = None
    in_scope_cost_layers: list[str] | None = None
    in_scope_service_families: list[str] | None = None
    base_currency: str | None = None
    price_year: int | None = None
    fx_convention: str | None = None
    analysis_horizon_years: int | None = None
    discount_rate_set_id: str | None = None
    engagement_purpose: str | None = None
    client_contact_status: str | None = None
    baseline_reference_period: str | None = None
    excluded_entities: list[str] | None = None


@router.put("/v1/outside-in/cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdate):
    """Mandatory intake block, partial update.

    Four fields - subject_entity_legal_name, entity_identifier,
    country_of_domicile, group_perimeter - are also written by
    entity_resolution.confirm(), which bumps perimeter_version and stamps
    entity_confirmed_by/at as the record of *who* confirmed *this* identity
    and perimeter (spec 0.1A). estimates:run stamps that same
    perimeter_version onto every snapshot as provenance. Letting this
    endpoint rewrite any of the four after confirmation would let an
    estimate's "perimeter v3, confirmed by Jane Okafor" go on describing a
    name or perimeter Jane never saw - the confirmation record would still
    read as current while silently describing something else. So once an
    entity is confirmed, those four fields are refused here; changing them
    means re-resolving and re-confirming through entities:resolve and
    :confirm-entity, which is the only path that bumps perimeter_version.
    """
    with S() as s:
        _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        fields = payload.model_dump(exclude_unset=True, exclude={"scope_mode", "region"})

        if entity_resolution.is_confirmed(s, case_id):
            locked = {"subject_entity_legal_name", "entity_identifier",
                     "country_of_domicile", "group_perimeter", "excluded_entities"}
            attempted = locked & set(fields)
            if attempted:
                raise HTTPException(409, {
                    "error": "entity already confirmed",
                    "locked_fields": sorted(attempted),
                    "detail": "these fields are set by confirming an entity "
                             "(spec 0.1A) and cannot be edited directly once "
                             "confirmed - re-resolve and confirm again via "
                             "entities:resolve / :confirm-entity instead"})

        if payload.scope_mode is not None:
            try:
                countries, region = scope.resolve(
                    s, scope_mode=payload.scope_mode, region=payload.region,
                    explicit_countries=payload.in_scope_countries)
            except ValueError as e:
                raise HTTPException(422, str(e))
            fields["in_scope_countries"] = countries
            fields["in_scope_region"] = region

        if not fields:
            return dict(_one_or_404(s, db.case, db.case.c.case_id, case_id, "case")._mapping)

        s.execute(update(db.case).where(db.case.c.case_id == case_id).values(**fields))
        s.commit()
        return dict(_one_or_404(s, db.case, db.case.c.case_id, case_id, "case")._mapping)


@router.get("/v1/outside-in/regions")
def list_regions():
    return {"regions": scope.region_choices(),
            "members": scope.REGION_COUNTRIES}


class ResolveIn(BaseModel):
    name_hint: str
    identifier_hint: str | None = None
    provider: str = "anthropic"
    mode: str = "LIVE"


@router.post("/v1/outside-in/cases/{case_id}/entities:resolve")
def resolve_entities(case_id: str, payload: ResolveIn):
    with S() as s:
        try:
            return entity_resolution.propose_candidates(
                s, case_id=case_id, name_hint=payload.name_hint,
                identifier_hint=payload.identifier_hint,
                provider=payload.provider, mode=payload.mode)
        except errors.ProviderUnavailable as e:
            raise HTTPException(503, f"LIVE run failed closed: {e}")
        except errors.ModeNotPermitted as e:
            raise HTTPException(422, str(e))
        except errors.StructuredOutputInvalid as e:
            raise HTTPException(502, f"model abstained: {e}")


@router.get("/v1/outside-in/cases/{case_id}/entity-candidates")
def entity_candidates(case_id: str):
    with S() as s:
        rows = s.execute(select(db.entity_candidate).where(
            db.entity_candidate.c.case_id == case_id).order_by(
            db.entity_candidate.c.match_score.desc())).all()
        return {"candidates": [dict(r._mapping) for r in rows]}


class ConfirmIn(BaseModel):
    candidate_id: str
    confirmed_by: str
    group_perimeter: str = "SINGLE_ENTITY"
    included_entities: list[str] = []
    excluded_entities: list[str] = []


@router.post("/v1/outside-in/cases/{case_id}:confirm-entity")
def confirm_entity(case_id: str, payload: ConfirmIn):
    with S() as s:
        return entity_resolution.confirm(
            s, case_id=case_id, candidate_id=payload.candidate_id,
            confirmed_by=payload.confirmed_by, group_perimeter=payload.group_perimeter,
            included=payload.included_entities, excluded=payload.excluded_entities)


# --------------------------------------------------------------- 0.1B known facts
class KnownFactIn(BaseModel):
    fact_class: str
    subject: str
    value_base: float | None = None
    value_low: float | None = None
    value_high: float | None = None
    unit: str | None = None
    currency: str | None = None
    asserted_by: str
    assertion_date: date
    basis: str
    verifiability: str
    self_reported_confidence: float | None = Field(default=None, ge=0, le=1)


@router.post("/v1/outside-in/cases/{case_id}/known-facts")
def add_known_fact(case_id: str, payload: KnownFactIn):
    with S() as s:
        try:
            return known_facts.register(s, case_id=case_id, **payload.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))


@router.get("/v1/outside-in/cases/{case_id}/known-facts")
def list_known_facts(case_id: str):
    with S() as s:
        rows = s.execute(select(db.known_fact).where(
            db.known_fact.c.case_id == case_id)).all()
        facts = []
        for r in rows:
            f = dict(r._mapping)
            # Surfaced, not merely stored: a corroborated fact that cannot be
            # traced to the call that corroborated it is an unsupported claim.
            f["corroborated_by_agent_run"] = f.pop("superseded_by", None)
            f["provenance"] = (
                f"/v1/outside-in/known-facts/{r.known_fact_id}/provenance"
                if f["corroborated_by_agent_run"] else None)
            facts.append(f)
        return {"known_facts": facts,
                "evidence_origin": known_facts.EVIDENCE_ORIGIN}


@router.get("/v1/outside-in/known-facts/{fact_id}/provenance")
def known_fact_provenance(fact_id: str):
    """Walk a corroborated fact back to the provider call behind it.

    fact -> corroborating agent run -> provider record -> the response and
    request identifiers the attestation quotes. A figure labelled
    EVIDENCED_PUBLIC rests on this chain, and until now the first link was
    written and shown nowhere.
    """
    with S() as s:
        try:
            return known_facts.provenance_chain(s, fact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/quantity-sources")
def quantity_sources(case_id: str):
    """Known facts eligible to supply a model quantity, with the evidence class
    each would carry. A corroborated fact enters as public evidence; an
    uncorroborated one as an assertion that triggers the 0.6A ceiling."""
    with S() as s:
        rows = s.execute(select(db.known_fact).where(
            db.known_fact.c.case_id == case_id)).all()
        out = {"footprint": [], "users": []}
        for r in rows:
            driver = known_facts.QUANTITY_CLASSES.get(r.fact_class)
            if not driver:
                continue
            out[driver].append({
                "known_fact_id": r.known_fact_id, "subject": r.subject,
                "value_base": str(r.value_base) if r.value_base is not None else None,
                "asserted_by": r.asserted_by,
                "corroboration_state": r.corroboration_state,
                "rights_cleared": r.rights_cleared,
                "eligible": bool(r.rights_cleared)
                            and r.corroboration_state != "CONTRADICTED",
                "would_carry_origin": known_facts.origin_for(r.corroboration_state)})
        return out


@router.post("/v1/outside-in/known-facts/{fact_id}:clear-rights")
def clear_rights(fact_id: str, payload: ClearRightsIn):
    with S() as s:
        return known_facts.clear_rights(s, fact_id, payload.cleared_by)


@router.get("/v1/outside-in/cases/{case_id}/known-fact-conflicts")
def list_conflicts(case_id: str, open_only: bool = True):
    with S() as s:
        return {"conflicts": known_facts.conflicts(s, case_id, open_only=open_only)}


@router.post("/v1/outside-in/known-fact-conflicts/{conflict_id}:resolve")
def resolve_conflict(conflict_id: str, payload: ResolveConflictIn):
    """Record why a nominated fact may differ from the figure in use.

    The fact still does not become the source - it still disagrees - but the
    estimate stops being blocked, with the reason attached to the snapshot.
    """
    with S() as s:
        try:
            return known_facts.resolve_conflict(
                s, conflict_id=conflict_id, resolution=payload.resolution,
                reason=payload.reason, resolved_by=payload.resolved_by)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/known-facts/{fact_id}:corroborate")
def corroborate(fact_id: str, payload: CorroborateIn):
    with S() as s:
        try:
            return known_facts.corroborate(s, known_fact_id=fact_id,
                                           provider=payload.provider,
                                           mode=payload.mode)
        except errors.ProviderUnavailable as e:
            raise HTTPException(503, f"LIVE run failed closed: {e}")
        except errors.StructuredOutputInvalid as e:
            raise HTTPException(502, f"model abstained: {e}")


# --------------------------------------------------------------- 0.1C pre-flight
@router.get("/v1/outside-in/cases/{case_id}/preflight")
def get_preflight(case_id: str):
    """Read-only. Returns the latest report without creating one."""
    with S() as s:
        row = preflight.latest(s, case_id)
        if row is None:
            raise HTTPException(404, "no pre-flight report; POST :run first")
        return {"case_id": case_id,
                "report_id": row.report_id, "blocked": row.blocked,
                "conditions": row.conditions,
                "acknowledged_by": row.acknowledged_by,
                "blocks": [c for c in row.conditions if c["state"] == "BLOCK"],
                "warns": [c for c in row.conditions if c["state"] == "WARN"]}


@router.post("/v1/outside-in/cases/{case_id}/preflight:run")
def run_preflight(case_id: str, payload: PreflightRunIn):
    """Creates a new report. Note the asymmetry with GET: reading must never
    create one, because a fresh report supersedes a prior acknowledgement.

    `case_id` is echoed so a caller holding a cached report can tell whether it
    belongs to the case now in context. Without it the interface had no way to
    detect that it was rendering one case's readiness under another's - which
    it was doing, because Streamlit session state outlives a case switch.
    """
    with S() as s:
        report = preflight.run(s, case_id=case_id, mode=payload.mode)
        return {"case_id": case_id, **report}


@router.post("/v1/outside-in/cases/{case_id}/preflight:acknowledge")
def ack_preflight(case_id: str, payload: PreflightAckIn):
    with S() as s:
        return preflight.acknowledge(s, report_id=payload.report_id,
                                     acknowledged_by=payload.acknowledged_by)


# --------------------------------------------------------------- 0.3B simulation
class FootprintRow(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    archetype: str = Field(min_length=1, max_length=48)
    sites: int = Field(ge=0, le=config.MAX_SIM_SITES)


class SimIn(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    ensemble_size: int = Field(default=25, ge=1, le=config.MAX_ENSEMBLE_SIZE)
    footprint: list[FootprintRow] = Field(min_length=1, max_length=500)


@router.post("/v1/outside-in/cases/{case_id}/simulations:run", status_code=202)
def run_simulation(case_id: str, payload: SimIn):
    """Queue a simulation. Returns 202 immediately; poll the run for progress.

    §16.1 requires this to be asynchronous, cancellable and resumable. It was a
    blocking endpoint that held a worker for up to a minute at the permitted
    bounds.
    """
    with S() as s:
        try:
            preflight.assert_clear_to_run(s, case_id)
        except PermissionError as e:
            raise HTTPException(409, str(e))
        # users_base and bandwidth_mbps_base were seeded and never loaded. Five
        # columns exist on the prior; three were read. The footprint therefore
        # implied a headcount the model discarded in favour of a flat default.
        arch = {r.archetype: {"dual_access_probability": float(r.dual_access_probability),
                              "primary_product": r.primary_product,
                              "backup_product": r.backup_product,
                              "users_base": r.users_base,
                              "bandwidth_mbps_base": r.bandwidth_mbps_base}
                for r in s.execute(select(db.archetype_prior)).all()}
        footprint = [r.model_dump() for r in payload.footprint]
        total_sites = sum(r["sites"] for r in footprint)
        if total_sites > config.MAX_SIM_SITES:
            raise HTTPException(422, f"total sites {total_sites} exceeds "
                                     f"MAX_SIM_SITES={config.MAX_SIM_SITES}")
        unknown = sorted({r["archetype"] for r in footprint} - set(arch))
        if unknown:
            raise HTTPException(422, f"unknown archetypes: {unknown}")

        # Ask before creating the row. The candidate must not count itself,
        # and a refused run should never have existed.
        try:
            jobs.admit(s)
        except jobs.QueueFull as exc:
            raise HTTPException(429, str(exc))

        rid = str(uuid.uuid4())
        s.execute(insert(db.simulation_run).values(
            simulation_run_id=rid, case_id=case_id,
            model_version=config.SIMULATION_MODEL_VERSION, seed=payload.seed,
            ensemble_size=payload.ensemble_size,
            params={"footprint": footprint},
            pinned_priors={"archetype_prior": arch},
            status=jobs.QUEUED, progress_completed=0,
            progress_total=payload.ensemble_size, cancel_requested=False))
        s.commit()

    jobs.submit(rid)
    return {"simulation_run_id": rid, "status": jobs.QUEUED,
            "total": payload.ensemble_size,
            "poll": f"/v1/outside-in/simulations/{rid}"}


@router.get("/v1/outside-in/simulations/{run_id}")
def simulation_status(run_id: str, include_output: bool = False):
    with S() as s:
        try:
            state = jobs.status(s, run_id)
            if include_output and state["status"] == jobs.SUCCEEDED:
                row = _one_or_404(s, db.simulation_run.c.output,
                                  db.simulation_run.c.simulation_run_id,
                                  run_id, "simulation run")
                state["output"] = row.output
            return state
        except jobs.RunNotFound as exc:
            raise HTTPException(404, str(exc))


@router.post("/v1/outside-in/simulations/{run_id}:cancel", status_code=202)
def cancel_simulation(run_id: str):
    """Cancellation is checked between passes, so completed work survives and
    the run can be resumed from where it stopped."""
    with S() as s:
        try:
            return jobs.cancel(s, run_id)
        except jobs.RunNotFound as exc:
            raise HTTPException(404, str(exc))


@router.post("/v1/outside-in/simulations/{run_id}:resume", status_code=202)
def resume_simulation(run_id: str):
    """Resume from the checkpoint.

    Cannot be refused on backlog: a resume finishes work already accepted, so it
    is exempt from admission control for the same reason reclaim is. If every
    worker is busy the run is queued and the drain collects it - see the test
    that asserts this does not raise when the backlog is full.
    """
    with S() as s:
        try:
            return jobs.resume(s, run_id)
        except jobs.RunNotFound as exc:
            raise HTTPException(404, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/simulations")
def list_simulations(case_id: str):
    with S() as s:
        rows = s.execute(select(
            db.simulation_run.c.simulation_run_id, db.simulation_run.c.seed,
            db.simulation_run.c.ensemble_size, db.simulation_run.c.model_version,
            db.simulation_run.c.output_hash, db.simulation_run.c.created_at,
            db.simulation_run.c.status, db.simulation_run.c.progress_completed,
            db.simulation_run.c.progress_total
        ).where(db.simulation_run.c.case_id == case_id).order_by(
            db.simulation_run.c.created_at.desc())).all()
        return {"runs": [dict(r._mapping) for r in rows]}


# --------------------------------------------------------------- 0.3A dispositions
@router.put("/v1/outside-in/cases/{case_id}/domain-dispositions")
def set_dispositions(case_id: str, records: list[DispositionIn]):
    """Manual disposition entry. Per-domain upsert, NOT delete-and-reinsert.

    This was a delete-and-reinsert, which meant every save silently nulled
    `evidence` and `agent_run_id` for all 24 domains - because this endpoint
    predates both columns and only ever wrote the six it knew about. Changing
    one dropdown on page 5 destroyed every research source fragment, every
    link to the provider call that produced it, and every client answer with
    its named respondent. The disposition *label* survived, so an
    EVIDENCED_PUBLIC row stayed labelled EVIDENCED_PUBLIC with nothing behind
    it - exactly what migration v11's own docstring says that column exists to
    prevent. Introduced in Tranche 1, worsened in Tranche 3, found in audit.

    Now: a domain whose disposition is unchanged keeps its provenance. A
    domain the analyst deliberately re-dispositions loses it, because sources
    gathered for one claim do not support a different one - but that is
    reported rather than silent, and the response names what was dropped.
    """
    records = [r.model_dump() for r in records]
    problems = dispositions.validate(records)
    with S() as s:
        existing = {r.domain_no: r for r in s.execute(
            select(db.domain_disposition).where(
                db.domain_disposition.c.case_id == case_id)).all()}
        incoming = {r["domain_no"] for r in records}

        # Domains absent from the payload are removed, preserving the previous
        # whole-case-replacement semantics the interface relies on.
        for domain_no in set(existing) - incoming:
            s.execute(delete(db.domain_disposition).where(
                db.domain_disposition.c.id == existing[domain_no].id))

        provenance_dropped = []
        for r in records:
            prev = existing.get(r["domain_no"])
            values = {"domain_name": r.get("domain_name", ""),
                      "disposition": r["disposition"], "reason": r.get("reason")}
            if prev is None:
                s.execute(insert(db.domain_disposition).values(
                    id=str(uuid.uuid4()), case_id=case_id,
                    estimate_snapshot_id=None, domain_no=r["domain_no"],
                    agent_run_id=None, evidence=None, **values))
                continue
            if prev.disposition != r["disposition"] and (prev.evidence
                                                         or prev.agent_run_id):
                # Deliberate re-disposition: the stored provenance was gathered
                # for the old claim and does not support the new one.
                provenance_dropped.append(
                    {"domain_no": r["domain_no"], "was": prev.disposition,
                     "now": r["disposition"],
                     "had_evidence": bool(prev.evidence),
                     "had_agent_run": bool(prev.agent_run_id)})
                values.update(agent_run_id=None, evidence=None)
            s.execute(update(db.domain_disposition)
                      .where(db.domain_disposition.c.id == prev.id)
                      .values(**values))
        s.commit()
    return {"stored": len(records), "publication_blockers": problems,
            "summary": dispositions.summarise(records),
            "provenance_dropped": provenance_dropped}


@router.get("/v1/outside-in/cases/{case_id}/domain-dispositions")
def get_dispositions(case_id: str):
    with S() as s:
        rows = s.execute(select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id).order_by(
            db.domain_disposition.c.domain_no)).all()
        recs = [dict(r._mapping) for r in rows]
        return {"dispositions": recs, "catalogue": dispositions.DOMAINS,
                "summary": dispositions.summarise(recs) if recs else None,
                "publication_blockers": dispositions.validate(recs) if recs else
                ["no dispositions recorded"]}


# --------------------------------------------------------------- 0.3A.2 domain research
class DomainResearchIn(BaseModel):
    agent_ids: list[str] | None = None       # default: both LLM-01 and LLM-08
    provider: str = "anthropic"
    overwrite: bool = False
    # Narrows the run to specific domains. The interface uses this to walk the
    # list one domain at a time: a full 17-domain run is minutes of LIVE
    # provider calls and source fetches, which no HTTP client will wait for.
    domain_nos: list[int] | None = None
    # Optional, same pattern as EstimateIn. Absent means a fresh scope per
    # call, so a deliberate re-run works; supplied means a repeat submission
    # of the *same* request returns the original runs instead of spending
    # twice at the provider.
    idempotency_key: str | None = None


@router.get("/v1/outside-in/cases/{case_id}/domain-research:prompt")
def domain_research_prompt(case_id: str, domain_no: int):
    """The exact system and user prompt this domain would be researched with.

    Read-only: builds the prompt, makes no provider call and writes nothing.
    The briefs in research.DOMAIN_BRIEFS are the main lever on research
    quality, and a lever nobody can see is one nobody tunes - the interface
    showed a disposition and a reason code, so a thin result and a badly
    worded brief were indistinguishable.

    Where the domain has already been researched, the prompt is hashed the
    same way the gateway hashes it (sha256 of system + prompt, llm_run.
    request_hash) and compared. A match proves the text below is what was
    actually sent, not a plausible reconstruction of it; a mismatch means the
    brief or the case scope has changed since that run, which is worth
    knowing before comparing outputs.
    """
    agent_id = research.DOMAIN_AGENT_MAP.get(domain_no)
    name = dict(dispositions.DOMAINS).get(domain_no)
    if name is None:
        raise HTTPException(404, f"domain {domain_no} is not one of the 24")
    if agent_id is None:
        return {"domain_no": domain_no, "domain_name": name, "agent_id": None,
                "researchable": False,
                "note": "benchmark-prior or simulation territory by design - "
                        "no agent researches this domain, so there is no prompt"}

    with S() as s:
        case_row = _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        research_policy = _research_policy(s)
        system = research.AGENT_SYSTEM_PROMPTS[agent_id]
        prompt = research._build_prompt(
            name, case_row, domain_no,
            context=research._build_context(s, case_row, domain_no),
            min_sources=research_policy.min_independent_sources_material_fact)
        request_hash = gateway._sha(system + prompt)

        # Did the run that produced the current disposition use this text?
        row = s.execute(select(db.domain_disposition.c.agent_run_id)
                        .where(db.domain_disposition.c.case_id == case_id,
                               db.domain_disposition.c.domain_no == domain_no)).first()
        matches, last_hash = None, None
        if row and row.agent_run_id:
            hit = s.execute(select(db.llm_run.c.request_hash)
                            .where(db.llm_run.c.agent_run_id == row.agent_run_id)
                            .order_by(db.llm_run.c.created_at.desc())).first()
            if hit:
                last_hash = hit.request_hash
                matches = (last_hash == request_hash)

    return {
        "domain_no": domain_no, "domain_name": name, "agent_id": agent_id,
        "researchable": True,
        "brief": research.DOMAIN_BRIEFS.get(domain_no),
        "system": system,
        "prompt": prompt,
        "tools": research._web_search_tool(
            research_policy.max_web_searches_per_domain),
        "request_hash": request_hash,
        "last_run_request_hash": last_hash,
        "matches_last_run": matches,
        "hash_note": (
            "sha256(system + prompt), the same value the gateway stores as "
            "llm_run.request_hash. matches_last_run is null when this domain "
            "has not been researched, false when the brief or case scope has "
            "changed since it was."),
    }


class PromoteIn(BaseModel):
    candidate_ids: list[str]
    promoted_by: str


@router.get("/v1/outside-in/cases/{case_id}/research-findings")
def research_findings(case_id: str):
    """Researched numbers the estimate could consume, and what has already
    been promoted. Read-only."""
    with S() as s:
        _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        return promotion.candidates(s, case_id)


@router.post("/v1/outside-in/cases/{case_id}/research-findings:promote")
def promote_research_findings(case_id: str, payload: PromoteIn):
    """Move selected findings into the footprint and the price priors.

    Named, like entity confirmation (0.1A): the system proposes, a person
    disposes. Prices land unapproved - research proposes a governed value
    under 18.1, it does not set one.
    """
    with S() as s:
        _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        try:
            div = policy.PriceDivergencePolicy.from_rows(
                _thresholds(s, "price_divergence_policy"))
        except policy.PolicyIncomplete as exc:
            raise HTTPException(409, {"error": "governed policy unusable",
                                      "detail": str(exc)})
        try:
            return promotion.promote(s, case_id=case_id,
                                     candidate_ids=payload.candidate_ids,
                                     promoted_by=payload.promoted_by,
                                     divergence_policy=div)
        except promotion.NotPromotable as exc:
            raise HTTPException(422, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/evidenced-footprint")
def evidenced_footprint(case_id: str):
    """The promoted footprint, in the shape simulations:run accepts - so the
    simulation page can start from evidence rather than from typing."""
    with S() as s:
        _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        return {"footprint": promotion.evidenced_footprint(s, case_id)}


@router.get("/v1/outside-in/cases/{case_id}/domain-research:plan")
def plan_domain_research(case_id: str, agent_ids: str | None = None,
                         overwrite: bool = False):
    """Which domains a research run would actually touch, in order.

    The interface needs this to walk the list one domain at a time and show
    progress. Computed here rather than in Streamlit so the domain-to-agent
    map has exactly one home (research.DOMAIN_AGENT_MAP) - a second copy in
    the interface would drift the moment the map is corrected.
    """
    wanted = ([a.strip() for a in agent_ids.split(",") if a.strip()]
              if agent_ids else ["LLM-01", "LLM-08"])
    with S() as s:
        _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        rows = s.execute(select(db.domain_disposition.c.domain_no,
                                db.domain_disposition.c.disposition)
                         .where(db.domain_disposition.c.case_id == case_id)).all()
    disposed = {r.domain_no for r in rows}
    # Protected from overwrite regardless - first-party client data is not
    # discarded as a side effect of re-running public research.
    client_confirmed = {r.domain_no for r in rows
                        if r.disposition == "CLIENT_CONFIRMED"}
    skipped = client_confirmed if overwrite else (disposed | client_confirmed)

    pending, already = [], []
    for no, name in dispositions.DOMAINS:
        if research.DOMAIN_AGENT_MAP.get(no) not in wanted:
            continue
        entry = {"domain_no": no, "domain_name": name,
                 "agent_id": research.DOMAIN_AGENT_MAP[no]}
        (already if no in skipped else pending).append(entry)
    return {"pending": pending, "skipped": already,
            "agent_ids": wanted, "overwrite": overwrite}


@router.post("/v1/outside-in/cases/{case_id}/domain-research:run")
def run_domain_research(case_id: str, payload: DomainResearchIn):
    """Runs LLM-01/LLM-08 research for whichever of the 24 domains they cover
    and do not already carry a disposition (or all of them, if overwrite=True).

    Composes with PUT .../domain-dispositions rather than replacing it: this
    writes only the domains DOMAIN_AGENT_MAP assigns to the requested agents,
    upserted one at a time, so a manual entry for domains outside that map -
    or a manual override the analyst made deliberately - is left alone unless
    overwrite is explicit.
    """
    with S() as s:
        research_policy = _research_policy(s)
        try:
            result = research.run_domain_research(
                s, case_id=case_id, agent_ids=payload.agent_ids,
                provider=payload.provider, research_policy=research_policy,
                overwrite=payload.overwrite, domain_nos=payload.domain_nos,
                idempotency_key=payload.idempotency_key)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return result


# --------------------------------------------------------------- V0 estimate
class EstimateIn(BaseModel):
    simulation_run_id: str
    # Optional. Absent means "derive it from the footprint" using the approved
    # users_base on each archetype - the topology already implies a headcount,
    # and a flat 5000 default made a 500-branch estate and a 5-DC estate cost
    # the same in platform terms. An explicit value still wins, and the
    # response records which was used.
    users: int | None = Field(default=None, ge=0, le=5_000_000)
    ops_cost_per_site_base: Decimal = Field(default=Decimal("900"), ge=0)
    # Reconciled and reported. Never used as the coverage denominator - that is
    # derived from the simulated scope and the priors.
    declared_spend_by_country: dict = {}
    # A quantity driver either comes from the analyst's typed scope (the
    # default) or from a registered known fact. Naming the fact is the only way
    # to claim the latter, so the link is traceable and the origin cannot be
    # asserted by the caller.
    footprint_known_fact_id: str | None = None
    users_known_fact_id: str | None = None
    idempotency_key: str | None = None


@router.post("/v1/outside-in/cases/{case_id}/estimates:run")
def run_estimate(case_id: str, payload: EstimateIn):
    with S() as s:
        try:
            preflight.assert_clear_to_run(s, case_id)
        except PermissionError as e:
            raise HTTPException(409, str(e))

        confidence_policy, coverage_policy, fact_policy = _policies(s)
        case_row = _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        sim = _one_or_404(s, db.simulation_run,
                          db.simulation_run.c.simulation_run_id,
                          payload.simulation_run_id, "simulation run")
        # A simulation from before the bandwidth dimension has product rows
        # with no bandwidth, and match_prior cannot price a circuit whose
        # requirement is unknown - so every circuit falls out as unpriced and
        # the coverage gate refuses at 0%. That refusal is true but it names
        # the wrong problem: nothing is wrong with the evidence, the run
        # predates the model. Caught here, where the remedy can be stated.
        _products = (sim.output or {}).get("products") or []
        if _products and not any("bandwidth_mbps" in p for p in _products):
            raise HTTPException(409, {
                "error": "simulation predates the bandwidth dimension",
                "simulation_model_version": sim.model_version,
                "current_model_version": config.SIMULATION_MODEL_VERSION,
                "detail": (
                    "This simulation's circuits carry no bandwidth, so none of "
                    "them can be matched to a price and the estimate would "
                    "report 0% coverage for a reason that has nothing to do "
                    "with coverage. Re-run the simulation on page 4 - the "
                    "footprint and seed are unchanged, so the result is "
                    "reproducible, not merely similar.")})

        if sim.status != jobs.SUCCEEDED or not sim.output:
            raise HTTPException(409, {
                "error": "simulation has not completed",
                "status": sim.status,
                "completed": sim.progress_completed, "total": sim.progress_total,
                "detail": "an estimate cannot be built from a partial ensemble"})

        disp = [dict(r._mapping) for r in s.execute(select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id)).all()]
        blockers = dispositions.validate(disp) if disp else ["no dispositions recorded"]
        if blockers:
            raise HTTPException(409, {"error": "V0 cannot publish", "blockers": blockers})

        countries = case_row.in_scope_countries or []
        prior_rows = s.execute(select(db.unit_cost_prior).where(
            db.unit_cost_prior.c.country.in_(countries or ["--"]),
            db.unit_cost_prior.c.approved.is_(True))).all()
        priors = {(r.country, r.product, r.bandwidth_mbps): {"low": r.low, "base": r.base,
                                           "high": r.high, "price_year": r.price_year}
                  for r in prior_rows}
        # Every approved prior, any country. Used only to *size* scope for the
        # coverage denominator - never to price a component (see derive_scope).
        sizing_priors = {(r.country, r.product, r.bandwidth_mbps): {"low": r.low, "base": r.base,
                                                  "high": r.high, "price_year": r.price_year}
                         for r in s.execute(select(db.unit_cost_prior).where(
                             db.unit_cost_prior.c.approved.is_(True))).all()}
        platform = {r.product: {"low": r.low, "base": r.base, "high": r.high}
                    for r in s.execute(select(db.platform_unit_cost).where(
                        db.platform_unit_cost.c.approved.is_(True))).all()}

        # Coverage denominator derived from the simulated scope, per
        # (country, product) pair - not accepted from the caller.
        scope = coverage.derive_scope(sim_output=sim.output, priors=priors,
                                      sizing_priors=sizing_priors)

        # Resolve quantity provenance. Unnamed drivers are the analyst's typed
        # scope; a named known fact is validated for rights, class and
        # corroboration, and a corroborated one enters as public evidence.
        sources = {}
        for driver, fact_id in (("footprint", payload.footprint_known_fact_id),
                                ("users", payload.users_known_fact_id)):
            if not fact_id:
                sources[driver] = {"origin": estimate.ANALYST_ENTERED_SCOPE,
                                   "known_fact_id": None}
                continue
            # Pass the figure the run actually uses, so a fact cannot be
            # credited as the source of a number it contradicts.
            used = sim.output.get("sites") if driver == "footprint" else payload.users
            try:
                sources[driver] = known_facts.resolve_quantity_source(
                    s, case_id=case_id, known_fact_id=fact_id, driver=driver,
                    value_used=used,
                    tolerance=fact_policy.agreement_tolerance)
            except known_facts.QuantityConflict as exc:
                raise HTTPException(409, {
                    "error": "nominated known fact disagrees with the run",
                    "detail": str(exc), "conflict_id": exc.conflict_id,
                    "resolve": f"/v1/outside-in/known-fact-conflicts/"
                               f"{exc.conflict_id}:resolve"})
            except ValueError as exc:
                raise HTTPException(422, str(exc))

        # Headcount: the analyst's figure if given, otherwise derived from the
        # footprint via each archetype's approved users_base. Which one was used
        # is reported, because a derived headcount and a typed one are different
        # claims and the reader should not have to guess.
        _implied = int(sim.output.get("implied_users") or 0)
        if payload.users is not None:
            _resolved_users, _users_source = payload.users, "ANALYST_SUPPLIED"
        elif _implied > 0:
            _resolved_users, _users_source = _implied, "DERIVED_FROM_FOOTPRINT"
        else:
            # No figure and nothing to derive from: refuse rather than fall back
            # to a constant. A platform cost computed on an invented headcount
            # is exactly the kind of unsourced number this bundle refuses.
            raise HTTPException(422, {
                "error": "no user count available",
                "detail": "None supplied, and the footprint implies none because "
                          "every archetype in it has users_base 0 (a DC-only "
                          "estate, for example). Supply `users` explicitly."})

        ops = D(payload.ops_cost_per_site_base)
        components, unpriced = estimate.build_components(
            sim_output=sim.output, users=_resolved_users,
            ops_cost_per_site={"low": ops * D("0.8"), "base": ops, "high": ops * D("1.3")},
            priors=priors,
            # build_components takes driver_origins/driver_refs keyed by the
            # driver names it uses internally ("sites", "users"). This call
            # passed footprint_origin= and users_origin=, which are not
            # parameters of that function at all, so every request raised
            # TypeError before reaching the calculation: estimates:run has
            # returned a bare 500 since the original build. The unit tests
            # call build_components directly with the correct keywords, so
            # they passed throughout - nothing exercised this route.
            driver_origins={"sites": sources["footprint"]["origin"],
                            "users": sources["users"]["origin"]},
            driver_refs={"sites": sources["footprint"].get("known_fact_id"),
                         "users": sources["users"].get("known_fact_id")},
            overlay_unit=platform.get("SDWAN_OVERLAY"),
            sse_unit=platform.get("SSE_LICENCE"))
        if not components:
            raise HTTPException(409, {"error": "no priced components", "unpriced": unpriced})

        layers_priced = {c.layer for c in components}
        cov = coverage.assess(
            scope=scope,
            layers_in_scope=case_row.in_scope_cost_layers or ["L0"],
            layers_priced=layers_priced,
            policy=coverage_policy,
            declared_spend_by_country=payload.declared_spend_by_country or None)
        if cov["status"] == "REFUSED":
            raise HTTPException(409, {"error": "V0 publication refused (0.3C)",
                                      "coverage": cov})

        cur = estimate.current_tco(components)
        lv = [dict(r._mapping) for r in s.execute(select(db.lever)).all()]
        levers_by_id = {l["lever_id"]: l for l in lv}
        scen = estimate.scenarios(components, lv)

        scenario_shares = {k: D(v["simulated_share"]) for k, v in scen.items()}
        sim_share = max(scenario_shares.values()) if scenario_shares else D(0)
        asserted = estimate.asserted_share(components)
        entered = estimate.entered_share(components)
        entered = estimate.entered_share(components)

        # Confidence components derived from the run, not supplied as literals.
        disp_summary = dispositions.summarise(disp)
        completeness = (D(disp_summary["total_domains"] - disp_summary["declared_unknown"])
                        / D(disp_summary["total_domains"]))
        priced_pairs = [r for r in scope if r["priced"]]
        prior_cov = D(len(priced_pairs)) / D(len(scope)) if scope else D(0)
        headline = max(scen, key=lambda k: D(scen[k]["gross_run_rate_savings"]["base"]))
        derived = confidence.derive_components(
            policy=confidence_policy,
            stage="V0", priced_spend_pct=cov["effective_coverage_pct"],
            origin_breakdown=cur["origin_breakdown"],
            domain_completeness=completeness,
            prior_recency=coverage.prior_recency(priors, case_row.price_year or 2026,
                                                 coverage_policy),
            prior_coverage=prior_cov,
            lever_stage_mix=estimate.lever_stage_mix(scen[headline], levers_by_id))
        conf = confidence.compute(
            policy=confidence_policy,
            current_baseline=derived["current_baseline"],
            target_cost=derived["target_cost"],
            realization=derived["realization"],
            simulated_share=sim_share, asserted_share=asserted,
            v0_status=cov["status"], drivers=derived["drivers"])

        snap_id = str(uuid.uuid4())
        s.execute(insert(db.estimate_snapshot).values(
            estimate_snapshot_id=snap_id, case_id=case_id, version_label="V0",
            v0_status=cov["status"],
            current_tco={**cur["by_layer"], "total": cur["total"]},
            target_tco={k: v["target_tco"] for k, v in scen.items()},
            scenarios=scen,
            gross_run_rate_savings={k: v["gross_run_rate_savings"] for k, v in scen.items()},
            confidence=conf,
            coverage={**cov, "unpriced_components": unpriced},
            simulated_share=float(sim_share), asserted_share=float(asserted),
            levers=[{"lever_id": l["lever_id"], "family": l["family"],
                     "scenario": l["scenario"], "cost_layers": l["cost_layers"],
                     "earliest_supported_stage": l["earliest_supported_stage"]} for l in lv],
            pins={"calculation_version": config.CALCULATION_VERSION,
                  "simulation_model_version": sim.model_version,
                  "simulation_seed": sim.seed, "simulation_output_hash": sim.output_hash,
                  "quantity_sources": sources,
                  "resolved_entity_id": case_row.resolved_entity_id,
                  "perimeter_version": case_row.perimeter_version,
                  "discount_rate_set_id": case_row.discount_rate_set_id,
                  "base_currency": case_row.base_currency,
                  "price_year": case_row.price_year,
                  "analysis_horizon_years": case_row.analysis_horizon_years,
                  "confidence_policy_set": confidence_policy.set_name,
                  "coverage_policy_set": coverage_policy.set_name}))
        s.commit()
        return {"estimate_snapshot_id": snap_id, "v0_status": cov["status"],
                "current_tco": cur["total"], "by_layer": cur["by_layer"],
                "origin_breakdown": cur["origin_breakdown"],
                "components": cur["components"], "scenarios": scen,
                "confidence": conf,
                "coverage": {**cov, "unpriced_components": unpriced},
                "simulated_share": str(sim_share),
                "simulated_share_by_scenario": {k: str(v) for k, v in scenario_shares.items()},
                "asserted_share": str(asserted),
                "entered_share": str(entered),
                "quantity_sources": sources,
                # Headcount provenance, and the bandwidth profile the topology
                # implies. The profile is REPORTED, not priced: unit_cost_prior
                # is keyed (country, product, cost_layer) with no speed
                # dimension, so a 100 Mbps branch and a 10 Gbps data centre on
                # the same product are priced identically. That is a real
                # limitation of the reference data and it is named here rather
                # than hidden - see the README.
                "users": _resolved_users,
                "users_source": _users_source,
                "users_implied_by_footprint": _implied,
                "bandwidth_profile": sim.output.get("bandwidth_profile", {}),
                "bandwidth_mbps_total": sim.output.get("bandwidth_mbps_total", 0),
                "bandwidth_is_priced": False,
                "uncorroborated_known_facts": known_facts.uncorroborated_count(s, case_id)}


@router.get("/v1/outside-in/cases/{case_id}/estimates")
def list_estimates(case_id: str):
    with S() as s:
        rows = s.execute(select(db.estimate_snapshot).where(
            db.estimate_snapshot.c.case_id == case_id).order_by(
            db.estimate_snapshot.c.created_at.desc())).all()
        return {"snapshots": [dict(r._mapping) for r in rows]}


# --------------------------------------------------------------- Tranche 2 (LLM-07, LLM-06)
class RecommendIn(BaseModel):
    mode: str = "LIVE"          # LIVE | DETERMINISTIC_ONLY - never inferred, never automatic
    provider: str = "anthropic"
    idempotency_key: str | None = None


class ApproveIn(BaseModel):
    approved_by: str            # a name, not a role or a team - see savings_advisory.approve


class NarrateIn(BaseModel):
    mode: str = "LIVE"
    provider: str = "anthropic"
    final: bool = False         # True is refused, not downgraded, if material and unapproved
    idempotency_key: str | None = None


def _recommendation_or_404(session, case_id: str, recommendation_id: str) -> dict:
    row = session.execute(select(db.recommendation).where(
        db.recommendation.c.recommendation_id == recommendation_id)).one_or_none()
    if row is None or row.case_id != case_id:
        raise HTTPException(404, f"recommendation {recommendation_id!r} not found for "
                                 f"case {case_id!r}")
    return dict(row._mapping)


@router.post("/v1/outside-in/cases/{case_id}/estimates/{estimate_snapshot_id}"
            "/recommendation:run")
def run_recommendation(case_id: str, estimate_snapshot_id: str, payload: RecommendIn):
    with S() as s:
        # Checked before recommend() runs, not after: recommend() creates a
        # real agent_run and, in LIVE mode, makes a real provider call. Catching
        # a case_id mismatch afterward would mean the call already happened.
        snap = s.execute(select(db.estimate_snapshot.c.case_id).where(
            db.estimate_snapshot.c.estimate_snapshot_id == estimate_snapshot_id)).first()
        if snap is None or snap.case_id != case_id:
            raise HTTPException(404, f"estimate snapshot {estimate_snapshot_id!r} not "
                                     f"found for case {case_id!r}")
        rp = _recommendation_policy(s)
        try:
            return savings_advisory.recommend(
                s, estimate_snapshot_id=estimate_snapshot_id, mode=payload.mode,
                provider=payload.provider, recommendation_policy=rp,
                idempotency_key=payload.idempotency_key)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except errors.ModeNotPermitted as exc:
            raise HTTPException(409, {"error": "execution mode refused", "detail": str(exc)})
        except errors.StructuredOutputInvalid as exc:
            raise HTTPException(502, {"error": "LLM-07 output invalid", "detail": str(exc)})
        except (errors.ProviderUnavailable, errors.LivenessProofFailed) as exc:
            raise HTTPException(503, {"error": "LLM-07 LIVE call failed", "detail": str(exc)})


@router.post("/v1/outside-in/cases/{case_id}/recommendations/{recommendation_id}:approve")
def approve_recommendation(case_id: str, recommendation_id: str, payload: ApproveIn):
    with S() as s:
        _recommendation_or_404(s, case_id, recommendation_id)
        try:
            return savings_advisory.approve(
                s, recommendation_id=recommendation_id, approved_by=payload.approved_by)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/cases/{case_id}/recommendations/{recommendation_id}"
            "/narrative:run")
def run_narrative(case_id: str, recommendation_id: str, payload: NarrateIn):
    with S() as s:
        _recommendation_or_404(s, case_id, recommendation_id)
        try:
            return savings_advisory.narrate(
                s, recommendation_id=recommendation_id, mode=payload.mode,
                provider=payload.provider, final=payload.final,
                idempotency_key=payload.idempotency_key)
        except PermissionError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except errors.ModeNotPermitted as exc:
            raise HTTPException(409, {"error": "execution mode refused", "detail": str(exc)})
        except errors.StructuredOutputInvalid as exc:
            raise HTTPException(502, {"error": "LLM-06 output invalid", "detail": str(exc)})
        except (errors.ProviderUnavailable, errors.LivenessProofFailed) as exc:
            raise HTTPException(503, {"error": "LLM-06 LIVE call failed", "detail": str(exc)})


@router.get("/v1/outside-in/cases/{case_id}/recommendations")
def list_recommendations(case_id: str):
    """Read-only - unlike re-calling recommend()/narrate(), which each create
    a new agent_run."""
    with S() as s:
        rows = s.execute(select(db.recommendation).where(
            db.recommendation.c.case_id == case_id).order_by(
            db.recommendation.c.created_at.desc())).all()
        return {"recommendations": [dict(r._mapping) for r in rows]}


@router.get("/v1/outside-in/cases/{case_id}/recommendations/{recommendation_id}")
def get_recommendation(case_id: str, recommendation_id: str):
    with S() as s:
        return _recommendation_or_404(s, case_id, recommendation_id)


# --------------------------------------------------------------- Tranche 3: V1 stage
class PrefillIn(BaseModel):
    mode: str = "LIVE"          # LIVE | DETERMINISTIC_ONLY - never inferred
    provider: str = "anthropic"
    overwrite: bool = False     # never overwrites an *answered* item regardless
    idempotency_key: str | None = None


class AnswerIn(BaseModel):
    question_key: str
    answer_value: str
    answered_by: str            # a named person at the client, never a role


class MapAnswersIn(BaseModel):
    mapped_by: str              # named person - this changes what the estimate rests on


class ResolveMappingIn(BaseModel):
    question_key: str
    resolution: str             # see questionnaire.RESOLUTIONS
    resolved_by: str
    note: str = ""              # mandatory for CLIENT_SUPERSEDES_PUBLIC


class StageAssessIn(BaseModel):
    target_stage: str = "V1"


class StageAckIn(BaseModel):
    report_id: str
    acknowledged_by: str


class StageAdvanceIn(BaseModel):
    target_stage: str = "V1"
    advanced_by: str


@router.post("/v1/outside-in/cases/{case_id}/questionnaire")
def create_questionnaire(case_id: str):
    with S() as s:
        try:
            return questionnaire.create(s, case_id=case_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/questionnaire")
def get_questionnaire(case_id: str):
    with S() as s:
        return questionnaire.load(s, case_id)


@router.post("/v1/outside-in/cases/{case_id}/questionnaire:prefill")
def prefill_questionnaire(case_id: str, payload: PrefillIn):
    with S() as s:
        try:
            return questionnaire.prefill(s, case_id=case_id, mode=payload.mode,
                                         provider=payload.provider,
                                         overwrite=payload.overwrite,
                                         idempotency_key=payload.idempotency_key)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/cases/{case_id}/questionnaire:answer")
def answer_questionnaire(case_id: str, payload: AnswerIn):
    with S() as s:
        try:
            return questionnaire.answer(s, case_id=case_id,
                                        question_key=payload.question_key,
                                        answer_value=payload.answer_value,
                                        answered_by=payload.answered_by)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/cases/{case_id}/questionnaire:map")
def map_questionnaire_answers(case_id: str, payload: MapAnswersIn):
    """Maps answered items onto the 0.3A disposition contract. Only upgrades a
    domain that held DECLARED_UNKNOWN, a benchmark prior or an analyst
    assertion; an answer meeting public evidence is flagged for adjudication
    rather than allowed to overwrite it."""
    with S() as s:
        try:
            return questionnaire.map_answers(s, case_id=case_id,
                                             mapped_by=payload.mapped_by)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/cases/{case_id}/questionnaire:resolve-mapping")
def resolve_questionnaire_mapping(case_id: str, payload: ResolveMappingIn):
    with S() as s:
        try:
            return questionnaire.resolve_mapping(
                s, case_id=case_id, question_key=payload.question_key,
                resolution=payload.resolution, resolved_by=payload.resolved_by,
                note=payload.note)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/questionnaire/conflicts")
def questionnaire_conflicts(case_id: str):
    with S() as s:
        return {"case_id": case_id,
                "conflicts": questionnaire.unresolved_conflicts(s, case_id)}


@router.post("/v1/outside-in/cases/{case_id}/stage:assess")
def assess_stage(case_id: str, payload: StageAssessIn):
    with S() as s:
        try:
            return stage.assess(s, case_id=case_id, target_stage=payload.target_stage)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.get("/v1/outside-in/cases/{case_id}/stage")
def get_stage(case_id: str, target_stage: str = "V1"):
    """Read-only: the case's current stage plus the latest readiness report,
    without creating one."""
    with S() as s:
        case_row = _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
        report = stage.latest(s, case_id, target_stage)
        return {"case_id": case_id,
                "current_stage": stage.current_stage(case_row),
                "advanced_by": case_row.stage_advanced_by,
                "advanced_at": case_row.stage_advanced_at,
                "assessable_targets": list(stage.TARGET_STAGES),
                "latest_report": None if report is None else {
                    "report_id": report.report_id,
                    "target_stage": report.target_stage,
                    "blocked": report.blocked,
                    "conditions": report.conditions,
                    "acknowledged_by": report.acknowledged_by}}


@router.post("/v1/outside-in/cases/{case_id}/stage:acknowledge")
def ack_stage(case_id: str, payload: StageAckIn):
    with S() as s:
        try:
            return stage.acknowledge(s, report_id=payload.report_id,
                                     acknowledged_by=payload.acknowledged_by)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.post("/v1/outside-in/cases/{case_id}/stage:advance")
def advance_stage(case_id: str, payload: StageAdvanceIn):
    with S() as s:
        try:
            return stage.advance(s, case_id=case_id,
                                 target_stage=payload.target_stage,
                                 advanced_by=payload.advanced_by)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


# --------------------------------------------------------------- 7.2C integrity
@router.get("/v1/agent-runs")
def agent_runs(case_id: str | None = None, limit: int = 50):
    with S() as s:
        q = select(db.agent_run).order_by(db.agent_run.c.started_at.desc()).limit(limit)
        if case_id:
            q = q.where(db.agent_run.c.case_id == case_id)
        return {"runs": [dict(r._mapping) for r in s.execute(q).all()]}


@router.get("/v1/agent-runs/{run_id}/provenance")
def provenance(run_id: str):
    with S() as s:
        rows = s.execute(select(db.llm_run).where(
            db.llm_run.c.agent_run_id == run_id)).all()
        return {"llm_runs": [dict(r._mapping) for r in rows]}


@router.get("/v1/agent-runs/rejections")
def rejections(limit: int = 50):
    with S() as s:
        rows = s.execute(select(db.rejected_run).order_by(
            db.rejected_run.c.created_at.desc()).limit(limit)).all()
        return {"rejections": [dict(r._mapping) for r in rows]}


class IncidentResolveIn(BaseModel):
    resolved_by: str = Field(min_length=1, max_length=120)
    resolution_note: str = Field(min_length=1)


@router.post("/v1/integrity/incidents/{incident_id}:resolve")
def resolve_integrity_incident(incident_id: str, payload: IncidentResolveIn):
    """Records that a named person investigated a finding and judged it
    addressed. Found in audit: `integrity_incident` had `resolved_at`,
    `resolved_by` and `resolution_note` columns, `GET /v1/integrity/incidents`
    took an `include_resolved` flag implying resolution existed, and nothing
    anywhere ever wrote any of the three. An incident, once raised by a
    migration, was permanent.

    That was not merely untidy. `_deep_health` caches only when
    `open_integrity_incidents` is 0, so one unresolvable incident meant deep
    health never cached again - every call re-running a schema query and two
    full policy validations. That is exactly the C3-08 defect this bundle
    already fixed once, silently resurrected by a different one.

    Resolving repairs nothing and deletes nothing. Quarantined rows stay in
    `audit.quarantined_row` in full; this only records the human judgement.
    The note is mandatory, because an incident closed without an explanation
    is worse than one left open - it looks handled.
    """
    with S() as s:
        row = s.execute(select(db.integrity_incident).where(
            db.integrity_incident.c.incident_id == incident_id)).one_or_none()
        if row is None:
            raise HTTPException(404, f"incident {incident_id!r} not found")
        if row.resolved_at is not None:
            raise HTTPException(409, {
                "error": "incident is already resolved",
                "resolved_by": row.resolved_by, "resolved_at": str(row.resolved_at)})
        s.execute(update(db.integrity_incident)
                  .where(db.integrity_incident.c.incident_id == incident_id)
                  .values(resolved_by=payload.resolved_by.strip(),
                          resolution_note=payload.resolution_note.strip(),
                          resolved_at=datetime.now(timezone.utc)))
        s.commit()
        quarantined = len(s.execute(select(db.quarantined_row.c.id).where(
            db.quarantined_row.c.incident_id == incident_id)).all())
    # The cache is keyed on a clean result, so a resolution has to invalidate
    # it or deep health keeps reporting the incident until the TTL expires.
    _DEEP_CACHE.update(at=None, value=None)
    return {"incident_id": incident_id, "resolved_by": payload.resolved_by.strip(),
            "quarantined_rows_retained": quarantined,
            "note": ("Resolution records a human judgement. Nothing was "
                     "repaired or deleted; quarantined rows are retained in "
                     "full in audit.quarantined_row.")}


@router.get("/v1/integrity/incidents")
def integrity_incidents(include_resolved: bool = False):
    """Findings the system raised about itself. A duplicate provider identifier
    discovered during a migration lands here rather than being repaired away."""
    with S() as s:
        q = select(db.integrity_incident).order_by(
            db.integrity_incident.c.detected_at.desc())
        if not include_resolved:
            q = q.where(db.integrity_incident.c.resolved_at.is_(None))
        incidents = [dict(r._mapping) for r in s.execute(q).all()]
        quarantined = s.execute(select(db.quarantined_row)).all()
    return {"incidents": incidents, "open": len(incidents),
            "quarantined_rows": len(quarantined),
            "note": ("Quarantined rows are preserved in full in "
                     "audit.quarantined_row. Nothing was deleted.")}


@router.get("/v1/integrity/attestation")
def attestation(days: int = 30):
    """A summary an operator can compare against the provider's own console.

    This is the only genuinely out-of-band check available: a different channel,
    on a different device, not reachable by anything that has compromised this
    host. Everything else in the provenance chain arrives over the same
    connection and can be forged together.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with S() as s:
        rows = s.execute(select(db.llm_run).where(
            db.llm_run.c.created_at >= since)).all()

    by_key: dict = {}
    strengths: dict = {}
    pins: dict = {}
    verifiable, sample = 0, []
    for r in rows:
        if r.provider_request_id:
            verifiable += 1
            if len(sample) < 20:
                sample.append({
                    "provider": r.provider, "model": r.model,
                    "provider_request_id": r.provider_request_id,
                    "provider_response_id": r.provider_response_id,
                    "provider_request_at": (r.provider_request_at.isoformat()
                                            if r.provider_request_at else None),
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens})
        k = (r.provider, r.model)
        agg = by_key.setdefault(k, {"calls": 0, "input_tokens": 0,
                                    "output_tokens": 0})
        agg["calls"] += 1
        agg["input_tokens"] += r.input_tokens or 0
        agg["output_tokens"] += r.output_tokens or 0
        st = r.provenance_strength or "UNKNOWN"
        strengths[st] = strengths.get(st, 0) + 1
        if r.tls_pin:
            pins.setdefault(r.provider, {}).setdefault(r.tls_pin, 0)
            pins[r.provider][r.tls_pin] += 1

    unpinned = sum(v for k, v in strengths.items() if k != "PINNED_AND_ENFORCED")
    return {
        "period_days": days,
        "since": since.isoformat(),
        "environment": config.environment(),
        "transport": gateway.transport_status(),
        "claimed": [{"provider": p, "model": m, **v} for (p, m), v in by_key.items()],
        "provenance_strength": strengths,
        "observed_tls_pins": pins,
        "runs_not_enforced": unpinned,
        # The provider's transport-issued request identifier is what its own
        # logs are indexed by. It is not a barrier to forgery - anyone
        # controlling the endpoint mints both identifiers - but it is what turns
        # this from "compare aggregate counts" into "confirm you served these
        # specific calls", which is a materially stronger question to be able to
        # ask through a channel this host does not control.
        "externally_verifiable_runs": verifiable,
        "total_runs": len(rows),
        "unverifiable_runs": len(rows) - verifiable,
        "require_provider_request_id": config.REQUIRE_PROVIDER_REQUEST_ID,
        "verification_sample": sample,
        "reconciliation": (
            "No automated provider fetch exists in this build. Submit figures "
            "read from the provider console to POST /v1/integrity/reconciliation; "
            "GET it for where the control stands."),
        "how_to_verify": (
            "Two checks, in order of strength. (1) Quote the provider_request_id "
            "values in verification_sample to the provider and ask whether it "
            "served them; those identifiers index its own logs. (2) Compare the "
            "call and token counts above against the provider console for the "
            "same period. A discrepancy this host cannot detect about itself "
            "will show in either."),
        "caveat": (
            "Counts above are this system's own claim. They are evidence only "
            "when checked against the provider's records through a channel this "
            "host does not control. Runs counted in unverifiable_runs carry no "
            "identifier to quote and cannot be spot-checked at all."),
    }


class BenchmarkExtractIn(BaseModel):
    text: str
    source_document: str
    source_locator: str | None = None
    source_org: str | None = None
    rights_basis: str = "PUBLISHED"
    as_of: str | None = None
    provider: str = "anthropic"


@router.post("/v1/benchmarks:extract")
def extract_benchmarks(payload: BenchmarkExtractIn):
    """Structure one source's text into benchmark observations.

    Text, not a file: the image carries no pptx/xlsx/pdf parser and does not
    want one. tools/ingest_benchmarks.py converts locally, so a confidential
    source never has to enter the container - only the extracted text and the
    observations, which carry a rights flag.
    """
    with S() as s:
        try:
            return benchmark_ingest.extract(
                s, text=payload.text, source_document=payload.source_document,
                source_locator=payload.source_locator,
                source_org=payload.source_org,
                rights_basis=payload.rights_basis, as_of=payload.as_of,
                provider=payload.provider)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except errors.ProviderUnavailable as exc:
            raise HTTPException(503, str(exc))
        except (errors.LivenessProofFailed, errors.StructuredOutputInvalid) as exc:
            raise HTTPException(502, str(exc))


@router.get("/v1/benchmarks/observations")
def list_benchmark_observations(metric: str | None = None,
                                rights_cleared: bool | None = None,
                                country: str | None = None):
    with S() as s:
        q = select(db.benchmark_observation)
        if metric:
            q = q.where(db.benchmark_observation.c.metric == metric)
        if rights_cleared is not None:
            q = q.where(db.benchmark_observation.c.rights_cleared.is_(rights_cleared))
        if country:
            q = q.where(db.benchmark_observation.c.country == country.upper())
        rows = s.execute(q.order_by(
            db.benchmark_observation.c.created_at.desc())).all()
        return {"observations": [dict(r._mapping) for r in rows]}


class ClearRightsIn(BaseModel):
    observation_ids: list[str]
    cleared_by: str


@router.post("/v1/benchmarks/observations:clear-rights")
def clear_benchmark_rights(payload: ClearRightsIn):
    """Named clearance. A benchmark from prior client work carries another
    client's commercial position and contributes to nothing until someone
    puts their name to that decision (2.4)."""
    with S() as s:
        try:
            return benchmark_ingest.clear_rights(
                s, observation_ids=payload.observation_ids,
                cleared_by=payload.cleared_by)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


class DeriveBandsIn(BaseModel):
    currency: str = "USD"
    price_year: int = 2026
    min_observations: int = 3
    dry_run: bool = True


@router.post("/v1/benchmarks/bands:derive")
def derive_benchmark_bands(payload: DeriveBandsIn):
    """Turn cleared observations into unapproved price bands, deterministically.

    dry_run by default: see what would be derived, and what is being skipped
    and why, before anything is written.
    """
    with S() as s:
        return benchmark_ingest.derive_bands(
            s, currency=payload.currency, price_year=payload.price_year,
            min_observations=payload.min_observations, dry_run=payload.dry_run)


@router.get("/v1/integrity/reachability")
def egress_reachability(case_id: str | None = None, place: str | None = None):
    """Prove the container can reach the public internet, with live evidence.

    /v1/health reports whether a key is set and pre-flight reports whether an
    adapter is configured; both pass on a container that can reach nothing.
    This one fetches data that changes - an independent clock, and the current
    weather where the subject entity is domiciled - so the answer can be read
    as true rather than taken on trust.
    """
    case_row = None
    if case_id:
        with S() as s:
            case_row = _one_or_404(s, db.case, db.case.c.case_id, case_id, "case")
    return reachability.check(case_row=case_row, place=place)


@router.get("/v1/integrity/tls-pins")
def tls_pins(days: int = 30):
    """Observed pins and the deadline for updating them.

    A pin cannot be configured before it has been seen, and it stops being valid
    when the certificate rotates - so both the value and its expiry are reported
    here. Reporting the expiry is what turns a switch to ENFORCE from a
    quarterly outage into a scheduled task.
    """
    from ..llm.providers import _transport
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with S() as s:
        rows = s.execute(select(db.llm_run.c.provider, db.llm_run.c.tls_pin,
                                db.llm_run.c.tls_cert_not_after)
                         .where(db.llm_run.c.created_at >= since)).all()

    seen: dict = {}
    latest_expiry: dict = {}
    for r in rows:
        if r.tls_pin:
            seen.setdefault(r.provider, {}).setdefault(r.tls_pin, 0)
            seen[r.provider][r.tls_pin] += 1
        if r.tls_cert_not_after:
            prev = latest_expiry.get(r.provider)
            if prev is None or r.tls_cert_not_after > prev:
                latest_expiry[r.provider] = r.tls_cert_not_after

    hosts = {"anthropic": "api.anthropic.com", "openai": "api.openai.com"}
    # Suggest the SPKI form only; a certificate hash would be reinstating the
    # defect this endpoint exists to help avoid.
    suggested = ",".join(
        f"{hosts.get(p, p)}:{pin}"
        for p, pins in sorted(seen.items())
        for pin in sorted(pins) if pin.startswith("sha256/"))
    cert_only = sorted(p for p, pins in seen.items()
                       if pins and not any(x.startswith("sha256/") for x in pins))
    expiry = {p: _transport.expiry_warning(v) for p, v in latest_expiry.items()}

    return {
        "observed": seen,
        "certificate_expiry": expiry,
        "warnings": [e["message"] for e in expiry.values()
                     if e and e.get("warn") and e.get("message")],
        "suggested_TLS_PINS": suggested,
        "providers_without_an_spki_pin": cert_only,
        "spki_warning": _transport.spki_warning(),
        "spki_note": ("An SPKI pin (sha256/...) survives a certificate renewal "
                      "because the key is unchanged. A certificate pin "
                      "(cert-sha256/...) does not, and will fail on the renewal "
                      "date above. Configure the SPKI form."
                      if cert_only else None),
        "current": gateway.transport_status(),
        "note": ("Verify these against the provider's published certificate before "
                 "enforcing. Observing a pin proves only what this host connected "
                 "to, which is the thing in question."),
    }














class ReconciliationIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    tier: str = Field(pattern="^[AB]$")
    period_start: datetime
    period_end: datetime
    reported_calls: int = Field(ge=0)
    reported_tokens: int = Field(ge=0)
    recorded_by: str = Field(min_length=1, max_length=120)
    source: str = reconciliation.MANUAL_CONSOLE


@router.get("/v1/integrity/reconciliation")
def reconciliation_state():
    """Where the control of last resort actually stands.

    Reports never-reconciled distinctly from reconciled-and-passing, and says
    plainly that no automated provider fetch exists. The previous version
    returned EXPECTED_PENDING, which reads as "the job has not run yet" when
    there was no job.
    """
    with S() as s:
        return reconciliation.state(s)


@router.post("/v1/integrity/reconciliation")
def submit_reconciliation(payload: ReconciliationIn):
    """Submit figures read from the provider's own console.

    This is the out-of-band half of the comparison and is deliberately manual:
    a usage figure fetched by this host is only as trustworthy as this host,
    which is the thing being checked.
    """
    with S() as s:
        try:
            return reconciliation.record(
                s, reconciliation_policy=_reconciliation_policy(s),
                provider=payload.provider, tier=payload.tier,
                period_start=payload.period_start, period_end=payload.period_end,
                reported_calls=payload.reported_calls,
                reported_tokens=payload.reported_tokens,
                environment=config.environment(), source=payload.source,
                recorded_by=payload.recorded_by)
        except reconciliation.SourceNotImplemented as exc:
            raise HTTPException(501, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
