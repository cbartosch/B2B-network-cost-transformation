"""What an estimate rests on, and what would make it better - computed.

An analyst asking "why is this number what it is" and "what should I go and
find" deserves an answer, and an LLM is the right way to turn a structured
answer into prose. It is the wrong way to work out the answer: a model asked
what is missing from an estimate will produce a plausible list, and a plausible
list of gaps is worse than none because it sends people to look for the wrong
things.

So everything factual here is derived from the snapshot and the case:

  * how each figure was reached - which method, which drivers, which origins
  * what is missing - unpriced scope, assumed topology, unresearched domains,
    uncorroborated assertions, an unallocated footprint, a typed anchor
  * what closing each gap would change, and roughly how much

The model receives this packet and answers questions about it. It computes
nothing, and the quality gate rejects an answer containing a figure the packet
does not contain - which is the only way to let a model discuss numbers without
letting it invent them.

Gaps are ordered by what they cap. A confidence ceiling that no amount of other
work can lift outranks a missing price in one country, because the second is
arithmetic and the first is a limit on the whole estimate.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from .. import db


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def build_packet(session, *, case_id: str, snapshot) -> dict:
    """Everything the explainer is allowed to know, and nothing else."""
    case_row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first()
    pins = snapshot.pins or {}
    coverage = snapshot.coverage or {}
    confidence = snapshot.confidence or {}
    scenarios = snapshot.scenarios or {}

    headline = None
    if scenarios:
        headline = max(scenarios, key=lambda k: float(
            (scenarios[k].get("gross_run_rate_savings") or {}).get("base") or 0))

    figures = {
        "current_annual_cost": (snapshot.current_tco or {}).get("base"),
        "headline_scenario": headline,
        "headline_savings_low": ((scenarios.get(headline) or {})
                                 .get("gross_run_rate_savings") or {}).get("low"),
        "headline_savings_base": ((scenarios.get(headline) or {})
                                  .get("gross_run_rate_savings") or {}).get("base"),
        "headline_savings_high": ((scenarios.get(headline) or {})
                                  .get("gross_run_rate_savings") or {}).get("high"),
        "confidence_score": confidence.get("score"),
        "confidence_band": confidence.get("band"),
        "effective_coverage_pct": coverage.get("effective_coverage_pct"),
        "priced_circuits": coverage.get("priced_circuits"),
        "total_circuits": coverage.get("total_circuits"),
        "asserted_share": snapshot.asserted_share,
        "simulated_share": snapshot.simulated_share,
    }

    method = pins.get("estimate_method", "BUILD_UP")
    derivation = {
        "method": method,
        "how": (
            "Sites were turned into circuits by the simulation, each circuit "
            "priced against an approved benchmark for its country, product and "
            "bandwidth, and savings applied as lever percentages against the "
            "cost layers each lever names."
            if method == "BUILD_UP" else
            "A disclosed annual cost line was multiplied by a governed "
            "addressable share to give the pool the transformation could touch, "
            "split across cost layers, and savings applied as lever "
            "percentages against that pool."),
        "spend_basis": coverage.get("spend_basis"),
        "coverage_basis": coverage.get("coverage_basis"),
        "calculation_version": pins.get("calculation_version"),
        "confidence_components": confidence.get("components") or {},
        "ceilings_applied": confidence.get("ceilings_applied") or [],
        "origin_mix": pins.get("origin_breakdown") or {},
        "anchor_basis": pins.get("anchor_basis") or {},
    }

    return {
        "case": {
            "subject": case_row.subject_entity_legal_name if case_row else None,
            "industry": case_row.industry if case_row else None,
            "in_scope_countries": list(
                (case_row.in_scope_countries if case_row else None) or []),
        },
        "snapshot_id": snapshot.estimate_snapshot_id,
        "version_label": snapshot.version_label,
        "v0_status": snapshot.v0_status,
        "figures": {k: (str(v) if v is not None else None)
                    for k, v in figures.items()},
        "derivation": derivation,
        "levers": snapshot.levers or [],
        "gaps": gaps(session, case_id=case_id, snapshot=snapshot),
        "rules": [
            "Every figure in an answer must already appear in this packet. "
            "The estimate is the authority; the explanation is not.",
            "A gap not in the gaps list is not a gap this system knows about, "
            "and saying otherwise sends someone to look for the wrong thing.",
            "Simulated structure is a sizing instrument and never evidence "
            "(0.3B). An assertion is not evidence until a public source "
            "corroborates it (0.1B).",
        ],
    }


def gaps(session, *, case_id: str, snapshot) -> list[dict]:
    """What is missing, computed - ordered by what it caps.

    A confidence ceiling no other work can lift outranks a missing price in one
    country: the second is arithmetic, the first is a limit on the estimate.
    """
    coverage = snapshot.coverage or {}
    confidence = snapshot.confidence or {}
    pins = snapshot.pins or {}
    found = []

    # 1 - the stage ceiling, which nothing at V0 can lift
    for ceiling in confidence.get("ceilings_applied") or []:
        found.append({
            "gap": "STAGE_CEILING", "detail": str(ceiling),
            "closes_with": "advancing past V0, which needs client data",
            "would_change": "the confidence band; no V0 work lifts this one",
            "caps": "the whole estimate", "priority": 1})

    # 2 - assertions standing in for evidence
    asserted = _dec(snapshot.asserted_share) or Decimal(0)
    if asserted > 0:
        found.append({
            "gap": "UNCORROBORATED_ASSERTION",
            "detail": f"{asserted:.0%} of value rests on an analyst assertion",
            "closes_with": "corroborating the known fact against a public source",
            "would_change": "lifts the 0.6A baseline ceiling",
            "caps": "current_baseline confidence", "priority": 2})

    # 3 - a typed anchor, where the method is ANCHOR
    anchor = pins.get("anchor_basis") or {}
    if anchor and anchor.get("anchor_origin") != "EVIDENCED_PUBLIC":
        found.append({
            "gap": "ASSERTED_ANCHOR",
            "detail": "the anchor is a typed figure, not a disclosed one",
            "closes_with": "researching domain 9 or 10 and promoting the "
                           "cost line",
            "would_change": "the estimate would report COMPLETE instead of "
                            "PARTIAL",
            "caps": "the whole anchor method", "priority": 2})

    # 4 - scope the model could not price
    unpriced = coverage.get("unpriced_pairs") or []
    if unpriced:
        found.append({
            "gap": "UNPRICED_SCOPE",
            "detail": f"{len(unpriced)} (country, product, bandwidth) "
                      f"combination(s) have no approved price",
            "closes_with": "researching domain 19, or ingesting a benchmark",
            "would_change": "raises effective coverage; the excluded scope "
                            "enters the total",
            "caps": "coverage", "priority": 3})

    # 5 - topology the case has not tested
    assumed = (pins.get("topology_basis") or {}).get("assumed_fields") or []
    if assumed:
        found.append({
            "gap": "ASSUMED_TOPOLOGY",
            "detail": f"{len(assumed)} site-type dimension(s) come from the "
                      f"seed rather than this case: {', '.join(assumed[:6])}",
            "closes_with": "researching domains 7, 8, 14 or 15 and promoting "
                           "the findings",
            "would_change": "the circuit mix and therefore the baseline",
            "caps": "how much of the topology is evidence", "priority": 3})

    # 6 - domains carrying no evidence
    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    unknown = [r for r in rows if r.disposition == "DECLARED_UNKNOWN"]
    partial = [r for r in unknown
               if r.reason == "PARTIAL_EVIDENCE_BELOW_THRESHOLD"]
    if partial:
        found.append({
            "gap": "PARTIAL_FINDING",
            "detail": f"{len(partial)} domain(s) found something below the "
                      f"source minimum: "
                      f"{', '.join(str(r.domain_no) for r in partial)}",
            "closes_with": "one more independent source, or accepting the "
                           "single source deliberately",
            "would_change": "those findings become promotable evidence",
            "caps": "domain completeness", "priority": 3})
    plain_unknown = [r for r in unknown if r.reason == "NO_PUBLIC_EVIDENCE"]
    if plain_unknown:
        found.append({
            "gap": "NO_EVIDENCE",
            "detail": f"{len(plain_unknown)} domain(s) found nothing: "
                      f"{', '.join(str(r.domain_no) for r in plain_unknown)}",
            "closes_with": "the client, or a retuned research brief",
            "would_change": "domain completeness, which feeds confidence",
            "caps": "domain completeness", "priority": 4})

    # 7 - a footprint total nobody split
    if (pins.get("footprint_basis") or {}).get("needs_split"):
        found.append({
            "gap": "UNALLOCATED_FOOTPRINT",
            "detail": "a registered site total is not split by country and "
                      "site type",
            "closes_with": "allocating it on the simulation page",
            "would_change": "every circuit's product and bandwidth",
            "caps": "the whole circuit mix", "priority": 2})

    return sorted(found, key=lambda g: g["priority"])
