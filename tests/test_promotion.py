"""Tier 3: a research finding reaching the numbers the estimate actually uses.

Before this, `quantities` was written into domain_disposition.evidence and
read by nothing - the footprint came from what an analyst typed, so a perfect
answer on domain 2 moved the confidence score and not one number in the
estimate. These cover the promotion path and, as importantly, its limits.
"""
import uuid

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import promotion


def _case_with_finding(session, quantity, disposition="EVIDENCED_PUBLIC"):
    case_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition=disposition, reason=None, agent_run_id=run_id,
        evidence={"quantities": [quantity],
                  "sources": [{"url": "https://example.com/ar"}]}))
    session.commit()
    return case_id, run_id


def test_a_site_count_reaches_the_footprint_the_simulation_reads(session):
    q = {"label": "WAREHOUSE", "value": 340, "unit": "sites",
         "country": "DE", "as_of": "2024-12-31"}
    case_id, run_id = _case_with_finding(session, q)

    cands = promotion.candidates(session, case_id)
    assert len(cands["footprint_candidates"]) == 1
    cid = cands["footprint_candidates"][0]["candidate_id"]

    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    fp = promotion.evidenced_footprint(session, case_id)
    assert fp == [{"country": "DE", "archetype": "WAREHOUSE", "sites": 340,
                   "as_of": "2024-12-31", "agent_run_id": run_id,
                   "promoted_by": "Priya Raman"}]


def test_promotion_requires_a_named_person(session):
    q = {"label": "WAREHOUSE", "value": 12, "unit": "sites", "country": "GB"}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    with pytest.raises(promotion.NotPromotable):
        promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                          promoted_by="")


def test_a_promoted_price_is_unapproved_and_carries_its_provenance(session):
    """18.1: research proposes a governed value, it does not set one. An
    approved row would put a model's answer straight into every estimate with
    no steward in between."""
    q = {"label": "DIA 100Mbps MRC", "value": 520, "unit": "USD/month",
         "country": "DE", "as_of": "2025"}
    case_id, run_id = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["price_candidates"][0]["candidate_id"]

    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.country == "DE",
        db.unit_cost_prior.c.product == "DIA",
        db.unit_cost_prior.c.approved.is_(False))).one()
    assert row.source_agent_run_id == run_id
    assert "Priya Raman" in row.source_note


def test_an_unusable_quantity_is_declined_rather_than_coerced(session):
    """A finding this model cannot consume is not a bad finding. Coercing
    'a large European network' into a site count would be silent; declining
    it is visible."""
    q = {"label": "network scale", "value": 220, "unit": "countries served"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    assert not cands["footprint_candidates"]
    assert len(cands["unclassified"]) == 1


def test_promoting_the_same_finding_twice_replaces_rather_than_duplicates(session):
    q = {"label": "WAREHOUSE", "value": 340, "unit": "sites", "country": "DE"}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="A")
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="B")
    fp = promotion.evidenced_footprint(session, case_id)
    assert len(fp) == 1 and fp[0]["promoted_by"] == "B"
