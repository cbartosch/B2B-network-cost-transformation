"""A steward's decision on a researched price outlives re-running research.

promote() deleted each researched price and re-inserted it unapproved, so
every run_samples --repromote undid every approval and every revocation since
the last one. US DIA at 10 Gbps and US MPLS at 1 Gbps were approved by name on
13 October and were unapproved, with no approver recorded, ten days later.

And the comparison promote() records was made in two currencies: a 104 AUD
plan judged against a 116-193 USD band. 26 of the 59 researched prices on the
card carry a verdict made that way.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import promotion


def _finding(session, *, value=520, currency="USD", country="DE"):
    case_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    quantity = {"label": "DIA 100Mbps MRC", "value": value,
                "unit": f"{currency}/month", "currency": currency,
                "country": country, "as_of": "2025", "bandwidth_mbps": 100,
                "candidates": [{"value": value,
                                "source_url": "https://example.com/tariff"}]}
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=19, domain_name="Pricing", disposition="EVIDENCED_PUBLIC",
        reason=None, agent_run_id=run_id,
        evidence={"quantities": [quantity],
                  "sources": [{"url": "https://example.com/tariff"}]}))
    session.commit()
    cid = promotion.candidates(session, case_id)["price_candidates"][0][
        "candidate_id"]
    return case_id, cid


def _promote(session, case_id, cid, by="Research run"):
    return promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                             promoted_by=by)


def _row(session, row_id="DE-DIA-100-researched"):
    session.expire_all()
    return session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == row_id)).one()


# ------------------------------------------- the decision outlives the rerun
def test_an_approval_survives_the_same_figure_being_promoted_again(session):
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.approve_price(session, row_id="DE-DIA-100-researched",
                            approved_by="Priya Raman")

    out = _promote(session, case_id, cid, by="the next rerun")

    row = _row(session)
    assert row.approved is True and row.approved_by == "Priya Raman"
    # The band approval set is the decision too, not only the flag.
    assert float(row.low) == pytest.approx(390) and float(row.high) == pytest.approx(650)
    assert [d["id"] for d in out["decisions_kept"]] == ["DE-DIA-100-researched"]


def test_a_revocation_survives_the_same_figure_being_promoted_again(session):
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.revoke_price(session, row_id="DE-DIA-100-researched",
                           revoked_by="Priya Raman", reason="consumer tariff")

    out = _promote(session, case_id, cid)

    row = _row(session)
    assert row.approved is False
    assert "consumer tariff" in row.source_note
    assert out["decisions_kept"][0]["decision"] == "REVOKED"
    assert out["decisions_kept"][0]["by"] == "Priya Raman"


def test_a_changed_figure_is_proposed_afresh_and_says_what_it_replaced(session):
    """A different number is a different claim. The approval was about 520,
    and carrying it to 610 would approve a figure nobody looked at."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.approve_price(session, row_id="DE-DIA-100-researched",
                            approved_by="Priya Raman")

    later, later_cid = _finding(session, value=610)
    out = _promote(session, later, later_cid)

    row = _row(session)
    assert row.approved is False and float(row.base) == 610
    assert "the earlier APPROVED decision (Priya Raman)" in row.source_note
    assert out["decisions_superseded"][0]["was"].startswith("520")
    assert not out["decisions_kept"]


def test_a_fresh_proposal_after_a_revocation_is_not_itself_read_as_revoked(
        session):
    """The note on the replacement names the revocation it replaced. Worded
    with the marker, the new row would read back as revoked - a proposal
    nobody has looked at, presented as one somebody turned down."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.revoke_price(session, row_id="DE-DIA-100-researched",
                           revoked_by="Priya Raman", reason="wholesale")
    later, later_cid = _finding(session, value=610)
    _promote(session, later, later_cid)

    row = _row(session)
    assert promotion.decision_on(row) is None
    assert "REVOKED decision" in row.source_note


def test_an_undecided_price_is_still_refreshed(session):
    """Nothing to protect, so a rerun replaces it as it always has - which is
    how a corrected figure reaches the card."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid, by="first run")
    out = _promote(session, case_id, cid, by="second run")

    assert "second run" in _row(session).source_note
    assert not out["decisions_kept"] and not out["decisions_superseded"]


# ------------------------------------- the comparison is made in one currency
def _benchmark(session, low=230, base=300, high=400, country="DE"):
    session.execute(insert(db.unit_cost_prior).values(
        id=f"{country}-DIA-100", country=country, product="DIA",
        cost_layer="L0", bandwidth_mbps=100, low=low, base=base, high=high,
        currency="USD", price_year=2026, approved=True))
    session.execute(insert(db.fx_rate).values(
        fx_rate_id=str(uuid.uuid4()), from_currency="USD", to_currency="GBP",
        rate=0.75, as_of=date(2026, 6, 30), convention="SPOT",
        source="test", evidence_grade="B"))
    session.commit()


def test_a_price_is_compared_in_the_benchmarks_currency(session):
    """185 GBP is 246.67 USD at 0.75 GBP to the dollar - inside a 230-400 USD
    band. Compared as quoted, 185 read as 20% below it."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(
        session, country="DE", product="DIA", value=185, bandwidth_mbps=100,
        currency="GBP")
    assert r["verdict"] == "WITHIN_BAND", r
    assert r["conversion"]["from"] == "GBP" and r["conversion"]["to"] == "USD"
    assert "185 GBP" in r["note"]


def test_without_a_rate_there_is_no_verdict(session):
    """A verdict on numbers in two currencies is the defect, so without a
    rate there is none - and it says which rate is missing."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(
        session, country="DE", product="DIA", value=38, bandwidth_mbps=100,
        currency="NZD")
    assert r["verdict"] == "NO_EXCHANGE_RATE" and r["material"] is False
    assert "NZD-USD" in r["note"]


def test_promotion_compares_in_the_currency_the_source_quoted(session):
    _benchmark(session)
    case_id, cid = _finding(session, value=185, currency="GBP")
    _promote(session, case_id, cid)
    note = _row(session).source_note
    assert "WITHIN_BAND" in note and "185.0 GBP" in note, note
