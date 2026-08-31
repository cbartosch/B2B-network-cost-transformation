"""Promotion: getting a research finding into the numbers the estimate uses.

Until this module existed, research was evidentially rigorous and analytically
inert. `quantities` was written into domain_disposition.evidence and read by
nothing; the footprint the simulation runs on came from what an analyst typed
on page 4, and circuit prices came from the seeded benchmark table. A perfect
answer on domain 2 moved the `evidenced` share of the confidence score and not
one number in the estimate.

Two rules shape what follows.

**Promotion is a person's act, not a consequence of researching.** A finding
appears here as a candidate; an analyst selects it and is named on the row.
That mirrors 0.1A, where the system proposes an entity and a named user
disposes, and it exists for the same reason: an automatic path from "a model
said so" to "the estimate now assumes so" is exactly the shape a bad number
takes on its way into a client deliverable.

**A promoted price is proposed, not approved.** Circuit prices are governed
reference data under 18.1: they carry an `approved` flag a steward sets.
Research writes them with approved=False, so they are visible, attributable
and inert until a steward accepts them. Site counts are case-scoped rather
than governed - they describe this client's estate, not a market rate - so
they land directly on the case with their provenance attached.

Every promoted row carries the agent_run_id that produced it, so the chain
from a number in the estimate back through the disposition, the provider call,
its liveness proof and the fetched source fragment stays unbroken.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select

from .. import db
from . import triangulate

# The archetypes the simulation understands. A quantity naming anything else
# cannot be promoted to a footprint row - it may be a perfectly good finding,
# but it is not one this model can consume, and silently coercing it would be
# worse than declining.
ARCHETYPES = {"BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC", "STORE"}
# HFC and PON are separate products, not variants of one: a shared coaxial
# segment and fibre to the premises price differently and are quoted
# separately in real tenders. The single BROADBAND band blended two
# distributions and described neither.
PRODUCTS = {"DIA", "MPLS", "ETHERNET", "BROADBAND_HFC", "BROADBAND_PON",
            "MOBILE_5G"}


class NotPromotable(ValueError):
    """The quantity does not carry what a promotion needs."""


def _as_int(value):
    """A band bound as a whole number, or None. Tolerates "341", "341.0" and
    a Decimal, because the band is serialised as a string for JSON storage."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _triangulated_index(evidence: dict) -> dict:
    """Bands by (label, country), so a promotion can carry the range and the
    conflict state rather than only the point the agent happened to state."""
    out = {}
    for t in (evidence or {}).get("triangulated") or []:
        key = ((t.get("label") or "").upper(),
               (t.get("country") or "").upper() or None)
        out[key] = t
    return out


def _quantities_for_case(session, case_id: str) -> list[dict]:
    """Every researched quantity on this case, with the disposition and agent
    run that produced it."""
    rows = session.execute(
        select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id)).all()
    out = []
    for r in rows:
        evidence = r.evidence or {}
        for i, q in enumerate(evidence.get("quantities") or []):
            if not isinstance(q, dict):
                continue
            band = _triangulated_index(evidence).get(
                ((q.get("label") or "").upper(),
                 (q.get("country") or "").upper() or None))
            out.append({
                "candidate_id": f"{r.domain_no}:{i}",
                "band": band,
                # Carried so the analyst sees what a finding is worth before
                # promoting it, and so UNRELIABLE can be refused.
                "reliability": (evidence or {}).get("reliability"),
                "domain_no": r.domain_no, "domain_name": r.domain_name,
                "disposition": r.disposition, "agent_run_id": r.agent_run_id,
                "sources": [s.get("url") for s in (evidence.get("sources") or [])
                            if isinstance(s, dict)],
                "quantity": q,
            })
    return out


def _classify(q: dict) -> str:
    """footprint | price | unclassified.

    Deliberately conservative: a quantity is only routed somewhere if it
    plainly carries what that destination needs. Everything else is reported
    as unclassified rather than guessed at, because a wrong promotion is
    silent and a declined one is visible.
    """
    label = str(q.get("label") or "").strip().upper()
    unit = str(q.get("unit") or "").strip().lower()
    country = str(q.get("country") or "").strip().upper()
    # Parsed, not type-checked. `value` became a string in 4.104.0 so that a
    # source stating "2 halls, 2.75 MW" could be kept as a qualitative finding
    # instead of failing the schema - and this isinstance check then classified
    # every quantity as unclassified, so nothing at all could be promoted. The
    # two changes were three releases apart and nothing connected them.
    if triangulate.parse_value(q.get("value")) is None:
        return "unclassified"
    if label in ARCHETYPES and len(country) == 2 and "site" in unit:
        return "footprint"
    # "DIA 100Mbps MRC" -> product is the first token.
    head = label.split()[0] if label else ""
    if head in PRODUCTS and len(country) == 2 and (
            "month" in unit or "mrc" in unit or "/mo" in unit):
        return "price"
    return "unclassified"


def candidates(session, case_id: str) -> dict:
    """What research has produced that the estimate could consume."""
    found = _quantities_for_case(session, case_id)
    buckets: dict[str, list] = {"footprint": [], "price": [], "unclassified": []}
    for entry in found:
        entry["target"] = _classify(entry["quantity"])
        buckets[entry["target"]].append(entry)
    promoted = session.execute(
        select(db.evidenced_footprint).where(
            db.evidenced_footprint.c.case_id == case_id)).all()
    return {
        "case_id": case_id,
        "footprint_candidates": buckets["footprint"],
        "price_candidates": buckets["price"],
        "unclassified": buckets["unclassified"],
        "already_promoted_footprint": [dict(r._mapping) for r in promoted],
        "note": (
            "A candidate is a researched number the estimate could use. "
            "Nothing here is in the estimate until a named person promotes it. "
            "Unclassified findings are not rejected - they are simply not in a "
            "shape this model consumes, and stay as evidence on the domain."),
    }



def compare_to_benchmark(session, *, country: str, product: str, value: float,
                         bandwidth_mbps: int | None = None,
                         policy=None) -> dict:
    """How far a researched price sits from the approved benchmark it would
    displace.

    Inside the approved low/high band is agreement - a benchmark is a range,
    and a figure within it corroborates rather than contradicts. Outside, the
    divergence is measured against the nearest edge rather than the midpoint,
    because the question a steward is answering is "how far outside the range
    we approved is this", not "how far from its centre".

    Returns a verdict either way. NO_BENCHMARK is not silence: a researched
    price for a country the model cannot currently price at all is the most
    valuable kind, and saying so is different from saying nothing was found.
    """
    # Matched on the tier, not on country and product alone. Since 4.53.0 a
    # product has several bandwidth bands - US DIA is 480/920/1340 base at
    # 100/500/1000 Mbps - and this used to take .first() with no ordering, so
    # a 100 Mbps price could be judged against the 1 Gbps band, and which
    # band it got was not even stable between runs. A corroborating price
    # then read as materially divergent, or the reverse.
    rows = session.execute(
        select(db.unit_cost_prior).where(
            db.unit_cost_prior.c.country == country,
            db.unit_cost_prior.c.product == product,
            db.unit_cost_prior.c.approved.is_(True))).all()
    if not rows:
        return {"verdict": "NO_BENCHMARK", "material": False,
                "note": (f"no approved benchmark for {country} {product} at any "
                         f"bandwidth, so this is new coverage rather than a "
                         f"correction - nothing to contradict")}

    row = next((r for r in rows if r.bandwidth_mbps == bandwidth_mbps), None)
    if row is None:
        tiers = sorted(r.bandwidth_mbps for r in rows if r.bandwidth_mbps)
        return {
            "verdict": "NO_BENCHMARK_AT_BANDWIDTH", "material": False,
            "observed_bandwidth_mbps": bandwidth_mbps,
            "benchmarked_bandwidths": tiers,
            "note": (f"{country} {product} is benchmarked at "
                     f"{tiers or 'no stated'} Mbps but not at "
                     f"{bandwidth_mbps or 'an unstated bandwidth'}. Comparing "
                     f"across tiers would be a comparison of different "
                     f"products, so this is reported rather than judged - a "
                     f"price at a tier the model cannot currently price is "
                     f"new coverage.")}

    low, base, high = float(row.low), float(row.base), float(row.high)
    if low <= value <= high:
        return {"verdict": "WITHIN_BAND", "material": False,
                "benchmark": {"low": low, "base": base, "high": high},
                "note": (f"{value} falls inside the approved band "
                         f"{low}-{high}; the research corroborates the "
                         f"benchmark")}

    edge = low if value < low else high
    # Guard a zero edge rather than dividing by it: a benchmark of 0 is a data
    # error, and reporting it as such beats a ZeroDivisionError inside a
    # promotion the analyst thought had succeeded.
    if edge == 0:
        return {"verdict": "BENCHMARK_UNUSABLE", "material": True,
                "benchmark": {"low": low, "base": base, "high": high},
                "note": (f"the approved band for {country} {product} has a "
                         f"zero edge, so divergence cannot be computed - the "
                         f"benchmark itself needs attention")}

    share = abs(value - edge) / abs(edge)
    threshold = float(policy.material_divergence_share) if policy else 0.25
    direction = "below" if value < low else "above"
    return {
        "verdict": "OUTSIDE_BAND",
        "material": share >= threshold,
        "benchmark": {"low": low, "base": base, "high": high},
        "divergence_share": round(share, 4),
        "direction": direction,
        "threshold": threshold,
        "note": (f"{value} is {share:.0%} {direction} the approved band "
                 f"{low}-{high}"
                 + (f", beyond the {threshold:.0%} materiality threshold - "
                    f"public research and the governed benchmark disagree "
                    f"materially and a steward should adjudicate before "
                    f"approving either"
                    if share >= threshold else
                    f", within the {threshold:.0%} materiality threshold")),
    }


def promote(session, *, case_id: str, candidate_ids: list[str],
            promoted_by: str, divergence_policy=None,
            accept_conflicts: bool = False) -> dict:
    """Move selected candidates into the numbers the estimate reads.

    Idempotent per (case, country, archetype) for footprint and per
    (country, product, price_year) for prices: promoting the same finding
    twice replaces rather than duplicates, so a corrected re-run does not
    leave the old figure sitting alongside the new one.
    """
    if not promoted_by:
        raise NotPromotable("promotion must be attributed to a named person")

    wanted = set(candidate_ids)
    entries = [e for e in _quantities_for_case(session, case_id)
               if e["candidate_id"] in wanted]
    missing = wanted - {e["candidate_id"] for e in entries}
    if missing:
        raise NotPromotable(f"no such candidate(s): {sorted(missing)}")

    now = datetime.now(timezone.utc)
    promoted_footprint, proposed_prices, declined = [], [], []

    for e in entries:
        q, target = e["quantity"], _classify(e["quantity"])
        band = e.get("band") or {}
        if band.get("review_required") and not accept_conflicts:
            # A quantity whose sources materially disagree is not ready to be
            # a number in an estimate. Promoting the midpoint would resolve
            # the disagreement by arithmetic and record no trace of it, which
            # is the outcome conflict retention exists to prevent. The
            # promotion is refused with the spread named; an analyst who has
            # looked and decided can pass accept_conflicts.
            declined.append({
                "candidate_id": e["candidate_id"],
                "reason": (f"sources disagree by "
                           f"{band.get('spread_share', 0):.0%} "
                           f"({band.get('low')} to {band.get('high')}) and the "
                           f"conflict has not been reviewed. Look at it and "
                           f"promote with accept_conflicts, or research the "
                           f"domain again.")})
            continue
        if target == "footprint":
            country = str(q["country"]).upper()
            archetype = str(q["label"]).upper()
            session.execute(delete(db.evidenced_footprint).where(
                db.evidenced_footprint.c.case_id == case_id,
                db.evidenced_footprint.c.country == country,
                db.evidenced_footprint.c.archetype == archetype))
            session.execute(insert(db.evidenced_footprint).values(
                id=str(uuid.uuid4()), case_id=case_id, country=country,
                archetype=archetype, sites=int(q["value"]),
                as_of=str(q.get("as_of") or ""), domain_no=e["domain_no"],
                # The band is stored as strings, and a price band's low is
                # "477.5" - int() on that raises rather than truncating. These
                # columns hold site counts, so rounding is right and crashing
                # on a decimal string is not.
                band_low=_as_int(band.get("low")),
                band_high=_as_int(band.get("high")),
                source_count=band.get("candidate_count"),
                agent_run_id=e["agent_run_id"],
                source_urls=e["sources"], promoted_by=promoted_by,
                promoted_at=now))
            promoted_footprint.append(
                {"country": country, "archetype": archetype,
                 "sites": int(q["value"]), "as_of": q.get("as_of")})
        elif target == "price":
            country = str(q["country"]).upper()
            product = str(q["label"]).split()[0].upper()
            _parsed = triangulate.parse_value(q["value"])
            if _parsed is None:
                declined.append({
                    "candidate_id": e["candidate_id"],
                    "reason": (f"{q.get('value')!r} is a finding stated in "
                               f"words, not a number, so it cannot be "
                               f"promoted to a priced input.")})
                continue
            value = float(_parsed)
            # A single observed price is a point, not a band. Recorded as the
            # base with the band left equal to it and approved=False, so a
            # steward has to widen it deliberately rather than the system
            # inventing a spread it has no evidence for.
            # Compare against the benchmark this would displace, before
            # writing. A researched price that contradicts a governed value is
            # the most informative outcome here and used to be the least
            # visible one: the row landed unapproved with no comparison
            # recorded, so a steward saw a number rather than a disagreement.
            cmp = compare_to_benchmark(session, country=country,
                                       product=product, value=value,
                                       bandwidth_mbps=int(mbps),
                                       policy=divergence_policy)
            # A price with no bandwidth is a valid observation and not a
            # usable prior: match_prior requires a tier, so a null-bandwidth
            # row would sit in unit_cost_prior pricing nothing while counting
            # as coverage. That is the exact condition migration v17 deletes
            # pre-split rows for, and writing it here anyway - which the first
            # version of this code did, with a comment calling the null
            # "visible" - reintroduced it two releases later. The observation
            # keeps its home in the benchmark vault; only a priceable row
            # reaches the reference table.
            mbps = q.get("bandwidth_mbps")
            if not mbps:
                declined.append({
                    "candidate_id": e["candidate_id"],
                    "reason": (f"{country} {product} price of {value} carries no "
                               f"bandwidth. A circuit rate without a tier cannot "
                               f"be matched to any circuit, so it is not "
                               f"promotable to a prior - re-run the domain, or "
                               f"set the tier on the observation first.")})
                continue
            row_id = f"{country}-{product}-{int(mbps)}-researched"
            session.execute(delete(db.unit_cost_prior).where(
                db.unit_cost_prior.c.id == row_id))
            session.execute(insert(db.unit_cost_prior).values(
                id=row_id, country=country, product=product, cost_layer="L0",
                bandwidth_mbps=int(mbps),
                low=value, base=value, high=value, currency="USD",
                price_year=2026, approved=False,
                source_agent_run_id=e["agent_run_id"],
                source_note=(f"researched from domain {e['domain_no']} by "
                             f"{promoted_by}; as_of {q.get('as_of') or 'unstated'}; "
                             f"single observation, band not yet set. "
                             f"vs benchmark: {cmp['verdict']} - {cmp['note']}")))
            proposed_prices.append(
                {"country": country, "product": product, "base": value,
                 "approved": False, "benchmark_comparison": cmp})
        else:
            declined.append({"candidate_id": e["candidate_id"],
                             "reason": "not in a shape the estimate consumes"})
    session.commit()

    material = [p for p in proposed_prices
                if (p.get("benchmark_comparison") or {}).get("material")]
    return {
        "promoted_footprint": promoted_footprint,
        "proposed_prices": proposed_prices,
        # Lifted out of the list rather than left to be noticed inside it. A
        # disagreement between public research and a governed benchmark is the
        # thing a steward most needs to see and the thing most easily missed
        # in a row of successful-looking promotions.
        "material_divergences": material,
        "declined": declined,
        "promoted_by": promoted_by,
        "note": (
            "Footprint rows are now available to the simulation page as the "
            "evidenced starting point. Prices are written unapproved and take "
            "no part in any estimate until a steward approves them - research "
            "proposes a governed value, it does not set one."),
    }


def evidenced_footprint(session, case_id: str) -> list[dict]:
    """The promoted footprint, with the provenance behind each count.

    Returns the band and source count as well as the figure. Those columns
    were added in v22 and this function did not select them, so the interface
    could only ever show a bare number - and a bare number cannot say whether
    three sources agreed on it or one source stated it, which is the
    difference between a count worth building an estimate on and one worth
    checking first.
    """
    rows = session.execute(
        select(db.evidenced_footprint)
        .where(db.evidenced_footprint.c.case_id == case_id)
        .order_by(db.evidenced_footprint.c.country,
                  db.evidenced_footprint.c.archetype)).all()
    return [{"country": r.country, "archetype": r.archetype, "sites": r.sites,
             "as_of": r.as_of, "agent_run_id": r.agent_run_id,
             "promoted_by": r.promoted_by, "domain_no": r.domain_no,
             "band_low": r.band_low, "band_high": r.band_high,
             "source_count": r.source_count,
             "source_urls": r.source_urls or []} for r in rows]
