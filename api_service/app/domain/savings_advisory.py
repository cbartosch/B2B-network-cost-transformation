"""Savings advisory and narrative (Tranche 2: LLM-07, LLM-06).

Read this before trusting what this module produces:

**"DETERMINISTIC_ONLY fallback" does not mean automatic failover.** gateway.py
already guarantees no automatic mode downgrade - a LIVE failure is FAILED, full
stop, and a deterministic result is "a new, explicitly requested run." Nothing
here catches a LIVE exception and silently retries deterministically. `mode` is
a caller's explicit choice at the top of recommend()/narrate(), same as
Tranche 1's LIVE-only calls, just with a second legitimate value now.

**The model never sets the dollar figure.** LLM-07 (LIVE) or the rule
(DETERMINISTIC_ONLY) choose a scenario_code and a percentile - a *choice*, not
a number. The actual gross_run_rate_savings is then looked up from
estimate_snapshot.scenarios, which domain/estimate.py already computed with
Decimal arithmetic before this module ever runs. Whatever the model's own text
might say about numbers is discarded; only the choice is read from it. This is
the same "model proposes, engine disposes" split Tranche 1 applied to
evidence - applied here to recommendations.

**Two labels, never conflated.** LIVE output is LLM_PROPOSED. DETERMINISTIC_ONLY
output is DETERMINISTIC_PROPOSED. Using LLM_PROPOSED for a rule-based pick
would misattribute it as the model's judgment - the same mode-honesty defect
the rest of this bundle's hardening pass has spent itself removing elsewhere.

**Material assumptions gate the narrative, not the recommendation.**
recommend() always writes a record, LIVE or deterministic, material or not -
refusing to record a recommendation because of what it contains would be a
different kind of dishonesty. What material_lever_share_threshold gates is
narrate(final=True): a lever whose saving_base is at or above the governed
share of current TCO makes the recommendation's narrative unavailable in final
form until a named person - never a role or a team, matching known_facts.py's
asserted_by - approves it. narrate(final=False) still produces a draft,
explicitly marked pending; every gate in this bundle refuses rather than
degrades, so a requested *final* narrative is refused outright rather than
silently handed back as a draft.

**deterministic_recommend() is not a new rule.** It reuses exactly the
'headline' selection run_estimate already trusted enough to derive realization
confidence from (highest base-case gross_run_rate_savings) - not a second,
independently-invented heuristic. It always proposes the base percentile:
choosing low or high is a judgment about this client's risk tolerance that a
fixed rule has no honest basis for.

**deterministic_narrate() is template assembly, not generated prose.** No
model is in the loop; it fills a fixed sentence structure with the
recommendation's own already-recalculated figures.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from .. import db
from ..llm import errors, gateway, registry
from .money import D
from .policy import RecommendationPolicy

log = logging.getLogger("workbench.savings_advisory")






def _fenced_scenario_summary(scenarios: dict) -> str:
    lines = []
    for code in sorted(scenarios):
        s = scenarios[code]
        levers = ", ".join(f"{l['family']} ({l['lever_id']})" for l in s["levers"]) or "none"
        savings = s["gross_run_rate_savings"]
        lines.append(
            f"{code} ({s['label']}): {s['savings_pct_base']} of current TCO; "
            f"gross run-rate savings low={savings['low']} base={savings['base']} "
            f"high={savings['high']}; simulated_share={s['simulated_share']}; "
            f"levers: {levers}")
    return gateway.fence("scenarios", "\n".join(lines))


def _build_recommend_prompt(snap) -> str:
    return (f"Review these modeled scenarios and choose one.\n"
            f"{_fenced_scenario_summary(snap.scenarios)}\n"
            f"Return the registered output schema.")


def _build_narrate_prompt(rec: dict, scenario: dict, *, final: bool) -> str:
    savings = rec["gross_run_rate_savings"]
    fenced = gateway.fence("decided_recommendation", (
        f"scenario={scenario['label']} ({rec['scenario_code']}); "
        f"percentile={rec['percentile']}; "
        f"gross_run_rate_savings={savings[rec['percentile']]}; "
        f"basis={rec['basis']}; "
        f"draft_or_final={'final' if final else 'draft'}"))
    return f"Write the narrative for this decided recommendation.\n{fenced}\nReturn the registered output schema."


def deterministic_recommend(scenarios: dict) -> tuple[str, str, str]:
    """The DETERMINISTIC_ONLY fallback for LLM-07. See the module docstring
    for why this is the 'headline' rule, not a new one, and why it always
    proposes the base percentile."""
    scenario_code = max(scenarios,
                        key=lambda k: D(scenarios[k]["gross_run_rate_savings"]["base"]))
    chosen = scenarios[scenario_code]
    basis = (
        f"Selected by rule, not judgment: {chosen['label']} shows the highest "
        f"projected gross run-rate savings at the base percentile "
        f"({chosen['savings_pct_base']} of current TCO) among the "
        f"{len(scenarios)} modeled scenarios. This does not weigh this "
        f"client's specific risk tolerance, timeline or transformation "
        f"appetite - request a LIVE-mode recommendation for that judgment.")
    return scenario_code, "base", basis


def deterministic_narrate(record: dict, scenario: dict) -> str:
    """The DETERMINISTIC_ONLY fallback for LLM-06. Template assembly, not
    generated prose - see the module docstring."""
    savings = record["gross_run_rate_savings"]
    levers = ", ".join(l["family"] for l in scenario["levers"]) or "no named levers"
    pending = (" This recommendation has not yet been approved by a named "
              "reviewer." if record.get("material_levers") and not record.get("approved_by")
              else "")
    return (
        f"Recommended scenario: {scenario['label']} ({record['scenario_code']}). "
        f"Projected gross run-rate savings at the {record['percentile']} percentile: "
        f"{savings[record['percentile']]} per year "
        f"({scenario['savings_pct_base']} of current total cost of ownership, base "
        f"case). Applied levers: {levers}. {record['basis']}{pending}")


def _material_levers(scenario: dict, current_tco_base: str,
                     policy: RecommendationPolicy) -> list[str]:
    base = D(current_tco_base)
    if not base:
        return []
    return [l["lever_id"] for l in scenario["levers"]
           if D(l["saving_base"]) / base >= policy.material_lever_share_threshold]


def recommend(session, *, estimate_snapshot_id: str, mode: str = "LIVE",
             provider: str = "anthropic",
             recommendation_policy: RecommendationPolicy,
             idempotency_key: str | None = None) -> dict:
    """LLM-07's entry point. mode is an explicit per-call choice - 'LIVE' or
    'DETERMINISTIC_ONLY' - never inferred, never switched automatically on a
    LIVE failure (see the module docstring). Raises LookupError for an unknown
    snapshot, ValueError for an unsupported mode, and lets
    errors.ProviderUnavailable / errors.LivenessProofFailed /
    errors.StructuredOutputInvalid propagate from a failed LIVE call rather
    than writing a record for it - a technical failure is not a
    recommendation, the same principle Tranche 1 applied to research."""
    if mode not in ("LIVE", "DETERMINISTIC_ONLY"):
        raise ValueError(f"recommend() supports LIVE or DETERMINISTIC_ONLY, not {mode!r}")
    for agent_id in ("LLM-07",):
        if agent_id not in registry.AGENTS:
            raise RuntimeError(f"{agent_id} is not registered - registry.py is out of sync")

    snap = session.execute(select(db.estimate_snapshot).where(
        db.estimate_snapshot.c.estimate_snapshot_id == estimate_snapshot_id)
    ).one_or_none()
    if snap is None:
        raise LookupError(f"no such estimate snapshot: {estimate_snapshot_id}")

    # Fresh per invocation unless the caller supplies one. A key stable
    # across calls returned the previous run, which execute() then refused as
    # already-completed - so a second recommendation on the same snapshot was
    # impossible. See research.py for the same fix.
    idem_key = idempotency_key or f"recommend:{uuid.uuid4()}"
    run_id = gateway.create_agent_run(session, agent_id="LLM-07", mode=mode,
                                      case_id=snap.case_id, idempotency_key=idem_key)

    if mode == "LIVE":
        # schemas.ScenarioSelection has no field for a monetary amount, so
        # the model cannot name one. The advisory figures are reloaded from
        # the snapshot after selection - a stronger guarantee than comparing
        # an echoed value for equality, because there is nothing to echo.
        # "did it pick a scenario that was actually offered" is now a gate
        # rather than an inline check, so a model choosing something that was
        # not on the table is a recorded verdict and a retry, not a raise.
        result, call = gateway.structured_call(
            session, agent_run_id=run_id, prompt_id="llm07.advisory.select",
            prompt=_build_recommend_prompt(snap), provider=provider,
            gate_context={"offered_scenarios": set(snap.scenarios or {})})
        parsed = result.model_dump()
        if (not isinstance(parsed, dict)
                or parsed.get("scenario_code") not in snap.scenarios
                or parsed.get("percentile") not in ("low", "base", "high")):
            gateway.fail(session, run_id,
                        "LLM-07 output was valid JSON but not the agreed shape, or "
                        "named an unknown scenario_code/percentile")
            raise errors.StructuredOutputInvalid(
                "LLM-07 output was valid JSON but not the agreed shape, or named "
                "an unknown scenario_code/percentile")
        scenario_code = parsed["scenario_code"]
        percentile = parsed["percentile"]
        basis = str(parsed.get("basis", ""))
        label = "LLM_PROPOSED"
    else:
        scenario_code, percentile, basis = deterministic_recommend(snap.scenarios)
        label = "DETERMINISTIC_PROPOSED"

    scenario = snap.scenarios[scenario_code]
    # Recalculated, not trusted: looked up from the snapshot's own
    # deterministic output for the chosen (scenario_code, percentile), never a
    # figure the model or the rule stated directly.
    savings = scenario["gross_run_rate_savings"]
    current_base = snap.current_tco.get("total", {}).get("base", "0")
    material = _material_levers(scenario, current_base, recommendation_policy)

    gateway.succeed(session, run_id, {"scenario_code": scenario_code,
                                      "percentile": percentile,
                                      "gross_run_rate_savings": savings})

    rec_id = str(uuid.uuid4())
    session.execute(insert(db.recommendation).values(
        recommendation_id=rec_id, estimate_snapshot_id=estimate_snapshot_id,
        case_id=snap.case_id, scenario_code=scenario_code, percentile=percentile,
        basis=basis, label=label, gross_run_rate_savings=savings,
        material_levers=material, approved_by=None, approved_at=None,
        agent_run_id=run_id, narrative=None, narrative_label=None,
        narrative_agent_run_id=None))
    session.commit()
    return _load(session, rec_id)


def approve(session, *, recommendation_id: str, approved_by: str) -> dict:
    """Same bar known_facts.py holds asserted_by to: a non-empty name is
    required; a role or a team is a convention this does not code-enforce
    beyond that, matching the precedent exactly rather than inventing a
    stricter check that would be inconsistent with it."""
    if not approved_by or not approved_by.strip():
        raise ValueError("approved_by is mandatory; an unattributed approval is rejected")
    rec = session.execute(select(db.recommendation).where(
        db.recommendation.c.recommendation_id == recommendation_id)).one_or_none()
    if rec is None:
        raise LookupError(f"no such recommendation: {recommendation_id}")
    session.execute(update(db.recommendation)
                    .where(db.recommendation.c.recommendation_id == recommendation_id)
                    .values(approved_by=approved_by.strip(),
                            approved_at=datetime.now(timezone.utc)))
    session.commit()
    return _load(session, recommendation_id)


def narrate(session, *, recommendation_id: str, mode: str = "LIVE",
           provider: str = "anthropic", final: bool = False,
           idempotency_key: str | None = None) -> dict:
    """LLM-06's entry point. final=True is refused (PermissionError) if the
    recommendation names a material lever with no named approval - refused,
    not silently downgraded to a draft, per the module docstring. final=False
    always produces a narrative, explicitly marked pending when applicable."""
    if mode not in ("LIVE", "DETERMINISTIC_ONLY"):
        raise ValueError(f"narrate() supports LIVE or DETERMINISTIC_ONLY, not {mode!r}")
    for agent_id in ("LLM-06",):
        if agent_id not in registry.AGENTS:
            raise RuntimeError(f"{agent_id} is not registered - registry.py is out of sync")

    rec_row = session.execute(select(db.recommendation).where(
        db.recommendation.c.recommendation_id == recommendation_id)).one_or_none()
    if rec_row is None:
        raise LookupError(f"no such recommendation: {recommendation_id}")
    rec = dict(rec_row._mapping)

    if final and rec["material_levers"] and not rec["approved_by"]:
        raise PermissionError(
            f"recommendation {recommendation_id} names material lever(s) "
            f"{rec['material_levers']} with no named approval yet - request "
            f"final=False for a draft, or approve it first")

    snap = session.execute(select(db.estimate_snapshot).where(
        db.estimate_snapshot.c.estimate_snapshot_id == rec["estimate_snapshot_id"])).one()
    scenario = snap.scenarios[rec["scenario_code"]]

    idem_key = idempotency_key or f"narrate:{uuid.uuid4()}"
    run_id = gateway.create_agent_run(session, agent_id="LLM-06", mode=mode,
                                      case_id=rec["case_id"], idempotency_key=idem_key)

    if mode == "LIVE":
        result, call = gateway.structured_call(
            session, agent_run_id=run_id, prompt_id="llm07.advisory.narrate",
            prompt=_build_narrate_prompt(rec, scenario, final=final),
            provider=provider)
        parsed = result.model_dump()
        if not isinstance(parsed, dict) or "narrative" not in parsed:
            gateway.fail(session, run_id,
                        "LLM-06 output was valid JSON but not the agreed shape")
            raise errors.StructuredOutputInvalid(
                "LLM-06 output was valid JSON but not the agreed shape")
        text = str(parsed["narrative"])
        label = "LLM_PROPOSED"
    else:
        text = deterministic_narrate(rec, scenario)
        label = "DETERMINISTIC_PROPOSED"

    if not final and rec["material_levers"] and not rec["approved_by"]:
        text = (f"[DRAFT - pending named approval for lever(s) "
                f"{rec['material_levers']}] " + text)

    gateway.succeed(session, run_id, {"narrative_label": label})
    session.execute(update(db.recommendation)
                    .where(db.recommendation.c.recommendation_id == recommendation_id)
                    .values(narrative=text, narrative_label=label,
                            narrative_agent_run_id=run_id))
    session.commit()
    return _load(session, recommendation_id)


def _load(session, recommendation_id: str) -> dict:
    row = session.execute(select(db.recommendation).where(
        db.recommendation.c.recommendation_id == recommendation_id)).one()
    return dict(row._mapping)
