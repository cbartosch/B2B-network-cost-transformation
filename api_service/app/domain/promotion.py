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

# The archetypes the simulation understands. A quantity naming anything else
# cannot be promoted to a footprint row - it may be a perfectly good finding,
# but it is not one this model can consume, and silently coercing it would be
# worse than declining.
ARCHETYPES = {"BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC", "STORE"}
PRODUCTS = {"DIA", "MPLS", "ETHERNET", "BROADBAND", "MOBILE_5G"}


class NotPromotable(ValueError):
    """The quantity does not carry what a promotion needs."""


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
            out.append({
                "candidate_id": f"{r.domain_no}:{i}",
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
    value = q.get("value")
    if not isinstance(value, (int, float)):
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


def promote(session, *, case_id: str, candidate_ids: list[str],
            promoted_by: str) -> dict:
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
                agent_run_id=e["agent_run_id"],
                source_urls=e["sources"], promoted_by=promoted_by,
                promoted_at=now))
            promoted_footprint.append(
                {"country": country, "archetype": archetype,
                 "sites": int(q["value"]), "as_of": q.get("as_of")})
        elif target == "price":
            country = str(q["country"]).upper()
            product = str(q["label"]).split()[0].upper()
            value = float(q["value"])
            # A single observed price is a point, not a band. Recorded as the
            # base with the band left equal to it and approved=False, so a
            # steward has to widen it deliberately rather than the system
            # inventing a spread it has no evidence for.
            row_id = f"{country}-{product}-researched"
            session.execute(delete(db.unit_cost_prior).where(
                db.unit_cost_prior.c.id == row_id))
            session.execute(insert(db.unit_cost_prior).values(
                id=row_id, country=country, product=product, cost_layer="L0",
                low=value, base=value, high=value, currency="USD",
                price_year=2026, approved=False,
                source_agent_run_id=e["agent_run_id"],
                source_note=(f"researched from domain {e['domain_no']} by "
                             f"{promoted_by}; as_of {q.get('as_of') or 'unstated'}; "
                             f"single observation, band not yet set")))
            proposed_prices.append(
                {"country": country, "product": product, "base": value,
                 "approved": False})
        else:
            declined.append({"candidate_id": e["candidate_id"],
                             "reason": "not in a shape the estimate consumes"})
    session.commit()

    return {
        "promoted_footprint": promoted_footprint,
        "proposed_prices": proposed_prices,
        "declined": declined,
        "promoted_by": promoted_by,
        "note": (
            "Footprint rows are now available to the simulation page as the "
            "evidenced starting point. Prices are written unapproved and take "
            "no part in any estimate until a steward approves them - research "
            "proposes a governed value, it does not set one."),
    }


def evidenced_footprint(session, case_id: str) -> list[dict]:
    """The promoted footprint, in the shape simulations:run expects."""
    rows = session.execute(
        select(db.evidenced_footprint)
        .where(db.evidenced_footprint.c.case_id == case_id)
        .order_by(db.evidenced_footprint.c.country,
                  db.evidenced_footprint.c.archetype)).all()
    return [{"country": r.country, "archetype": r.archetype, "sites": r.sites,
             "as_of": r.as_of, "agent_run_id": r.agent_run_id,
             "promoted_by": r.promoted_by} for r in rows]
