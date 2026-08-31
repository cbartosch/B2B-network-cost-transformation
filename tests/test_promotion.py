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


# --- researched price vs the benchmark it would displace --------------------
def _benchmark(session, country="DE", product="DIA", low=420, base=580, high=800):
    session.execute(insert(db.unit_cost_prior).values(
        id=f"{country}-{product}", country=country, product=product,
        cost_layer="L0", low=low, base=base, high=high, currency="USD",
        price_year=2026, approved=True))
    session.commit()


def _policy(share="0.25"):
    from decimal import Decimal
    from app.domain.policy import PriceDivergencePolicy
    return PriceDivergencePolicy(set_name="t",
                                 material_divergence_share=Decimal(share))


def test_a_price_inside_the_band_corroborates_rather_than_contradicts(session):
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=520, policy=_policy())
    assert r["verdict"] == "WITHIN_BAND" and r["material"] is False


def test_a_materially_divergent_price_is_flagged_not_absorbed(session):
    """The gap this closes: a researched price landed unapproved with no
    comparison recorded, so a figure 60% off the governed band looked exactly
    like one that confirmed it. The disagreement is the finding."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=1280, policy=_policy())
    assert r["verdict"] == "OUTSIDE_BAND" and r["material"] is True
    assert r["direction"] == "above"


def test_divergence_is_measured_from_the_nearest_edge_not_the_midpoint(session):
    """A benchmark is a range. Measuring from the centre would call a price
    just outside a wide band a large disagreement."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=880, policy=_policy())
    assert r["divergence_share"] == pytest.approx(80 / 800, abs=1e-4)
    assert r["material"] is False


def test_a_country_with_no_benchmark_is_new_coverage_not_silence(session):
    r = promotion.compare_to_benchmark(session, country="AE", product="DIA",
                                       value=1300, policy=_policy())
    assert r["verdict"] == "NO_BENCHMARK" and r["material"] is False


def test_promotion_records_the_comparison_where_a_steward_will_see_it(session):
    _benchmark(session)
    q = {"label": "DIA 100Mbps MRC", "value": 1280, "unit": "USD/month",
         "country": "DE", "as_of": "2025"}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["price_candidates"][0]["candidate_id"]

    out = promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                            promoted_by="Priya Raman",
                            divergence_policy=_policy())

    assert len(out["material_divergences"]) == 1
    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == "DE-DIA-researched")).one()
    assert row.approved is False
    assert "OUTSIDE_BAND" in row.source_note


def test_the_evidenced_footprint_carries_its_provenance(session):
    """The band and source count were added to the table in v22 and the
    accessor never selected them, so the interface could only show a bare
    number. A bare number cannot say whether three sources agreed on it or
    one source stated it - the difference between a count worth building an
    estimate on and one worth checking first."""
    q = {"label": "STORE", "value": 371, "unit": "sites", "country": "DE",
         "as_of": "2023"}
    case_id, run_id = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    row = promotion.evidenced_footprint(session, case_id)[0]
    for field in ("band_low", "band_high", "source_count", "domain_no",
                  "source_urls", "agent_run_id", "as_of", "promoted_by"):
        assert field in row, f"{field} is not returned to the interface"
    assert row["agent_run_id"] == run_id
