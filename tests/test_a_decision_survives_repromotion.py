"""A steward's decision on a researched price outlives re-running research.

promote() deleted each researched price and re-inserted it unapproved, so
every run_samples --repromote undid every approval and every revocation since
the last one. US DIA at 10 Gbps and US MPLS at 1 Gbps were approved by name on
13 October and were unapproved, with no approver recorded, ten days later.

Keeping a decision only when the same figure came back was not enough: one
row stands for a key across every company, and the companies disagree. So
promotion never writes over a decided row, and reports a different figure as
a challenge instead.

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


def test_a_different_figure_is_reported_and_the_approval_stands(session):
    """Another company's research for the same key. The approval was about
    520; replacing it with an unapproved 610 takes an approved price off the
    card because one search found another number."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.approve_price(session, row_id="DE-DIA-100-researched",
                            approved_by="Priya Raman")

    later, later_cid = _finding(session, value=610)
    out = _promote(session, later, later_cid)

    row = _row(session)
    assert row.approved is True and float(row.base) == 520
    challenge = out["decisions_challenged"][0]
    assert challenge["found"].startswith("610")
    assert challenge["decided"].startswith("520")
    assert not out["decisions_kept"]


def test_a_different_figure_does_not_reopen_a_revocation(session):
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.revoke_price(session, row_id="DE-DIA-100-researched",
                           revoked_by="Priya Raman", reason="wholesale")
    later, later_cid = _finding(session, value=610)
    out = _promote(session, later, later_cid)

    row = _row(session)
    assert promotion.decision_on(row)["decision"] == "REVOKED"
    assert float(row.base) == 520
    assert out["decisions_challenged"][0]["decision"] == "REVOKED"


def test_a_decision_survives_companies_that_disagree(session):
    """What the first rerun after the approvals did. One row stands for US DIA
    at 100 Mbps across every company, research found it at 333, 492, 625 and
    641, and promotion runs company by company - so the first with another
    figure replaced the approval, and every one after it priced without it."""
    first, first_cid = _finding(session, value=520)
    _promote(session, first, first_cid)
    promotion.approve_price(session, row_id="DE-DIA-100-researched",
                            approved_by="Priya Raman")

    for value in (610, 520, 480):
        case_id, cid = _finding(session, value=value)
        _promote(session, case_id, cid)
        row = _row(session)
        assert row.approved is True and float(row.base) == 520, value


def test_a_reopened_price_is_a_proposal_again(session):
    """Reopening returns the row to the queue, so the next run refreshes it
    like any undecided price - the revocation it reopened does not linger as
    a decision nobody holds any more."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid)
    promotion.revoke_price(session, row_id="DE-DIA-100-researched",
                           revoked_by="Priya Raman", reason="wholesale")
    promotion.reopen_price(session, row_id="DE-DIA-100-researched",
                           reopened_by="A reviewer", reason="source traced")
    assert promotion.decision_on(_row(session)) is None

    later, later_cid = _finding(session, value=610)
    out = _promote(session, later, later_cid)
    assert float(_row(session).base) == 610
    assert not out["decisions_challenged"]


def test_an_undecided_price_is_still_refreshed(session):
    """Nothing to protect, so a rerun replaces it as it always has - which is
    how a corrected figure reaches the card."""
    case_id, cid = _finding(session)
    _promote(session, case_id, cid, by="first run")
    out = _promote(session, case_id, cid, by="second run")

    assert "second run" in _row(session).source_note
    assert not out["decisions_kept"] and not out["decisions_challenged"]


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
