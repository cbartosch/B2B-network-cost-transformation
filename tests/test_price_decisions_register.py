"""A register of decisions on researched prices, applied by approve_prices.

The tool approved named rows one at a time at the card's width. Deciding 59
prices - some at a band their source states, most rejected with a reason -
needed a record of what was decided and why, applied the same way every
time, and safe to apply again.
"""
import csv
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import promotion

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "approve_prices", ROOT / "tools" / "approve_prices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _promoted(session, row_id, base, currency="USD"):
    country, product, mbps, _ = row_id.split("-")
    session.execute(insert(db.unit_cost_prior).values(
        id=row_id, country=country, product=product, cost_layer="L0",
        bandwidth_mbps=int(mbps), low=base, base=base, high=base,
        currency=currency, price_year=2026, approved=False,
        evidence_grade="C", price_basis="PROMOTED",
        source_note="researched from domain 19"))
    session.commit()


def _row(session, row_id):
    session.expire_all()
    return session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == row_id)).one()


LINES = [
    {"id": "US-DIA-100-researched", "decision": "APPROVE", "base": "492",
     "currency": "USD", "band_low": "333", "band_high": "641",
     "reason": "market median"},
    {"id": "GB-DIA-200-researched", "decision": "APPROVE", "base": "200",
     "currency": "GBP", "band_low": "", "band_high": "",
     "reason": "published tariff"},
    {"id": "DE-DIA-500-researched", "decision": "REJECT", "base": "31",
     "currency": "EUR", "band_low": "", "band_high": "",
     "reason": "wholesale price cap"},
    {"id": "ES-DIA-100-researched", "decision": "HOLD", "base": "160",
     "currency": "EUR", "band_low": "", "band_high": "",
     "reason": "single reseller"},
]


@pytest.fixture()
def priced(session):
    _promoted(session, "US-DIA-100-researched", 492)
    _promoted(session, "GB-DIA-200-researched", 200, "GBP")
    _promoted(session, "DE-DIA-500-researched", 31, "EUR")
    _promoted(session, "ES-DIA-100-researched", 160, "EUR")
    return session


def test_each_line_brings_its_row_to_the_state_it_asks_for(priced):
    _tool().apply_decisions(priced, LINES, by="Christian Bartosch")

    us = _row(priced, "US-DIA-100-researched")
    assert us.approved and us.approved_by == "Christian Bartosch"
    # The band the source states, not the card's width.
    assert (float(us.low), float(us.high)) == (333, 641)

    gb = _row(priced, "GB-DIA-200-researched")
    assert gb.approved and (float(gb.low), float(gb.high)) == (150, 250)

    de = _row(priced, "DE-DIA-500-researched")
    assert not de.approved and "wholesale price cap" in de.source_note
    assert promotion.decision_on(de)["decision"] == "REVOKED"

    # Held: still not pricing, and kept at the figure it was held at.
    es = _row(priced, "ES-DIA-100-researched")
    assert not es.approved
    assert promotion.decision_on(es)["decision"] == "HELD"


def test_applying_the_register_twice_changes_nothing(priced):
    tool = _tool()
    tool.apply_decisions(priced, LINES, by="Christian Bartosch")
    again = tool.apply_decisions(priced, LINES, by="Christian Bartosch")

    assert [outcome for _id, outcome, _d in again] == [
        "UNCHANGED", "UNCHANGED", "UNCHANGED", "UNCHANGED"]
    # A second revocation would append a second reason to the note.
    note = _row(priced, "DE-DIA-500-researched").source_note
    assert note.count(promotion.REVOKED_MARK) == 1


def test_a_malformed_line_applies_nothing(priced):
    """Validated whole first: half a register applied is a rate card nobody
    decided."""
    bad = LINES + [{"id": "X-DIA-1-researched", "decision": "MAYBE",
                    "band_low": "", "band_high": "", "reason": ""}]
    with pytest.raises(promotion.NotPromotable, match="MAYBE"):
        _tool().apply_decisions(priced, bad, by="Christian Bartosch")
    assert not _row(priced, "US-DIA-100-researched").approved


def test_a_rejection_needs_its_reason(priced):
    line = {**LINES[2], "reason": " "}
    with pytest.raises(promotion.NotPromotable, match="reason"):
        _tool().apply_decisions(priced, [line], by="Christian Bartosch")


def test_a_hold_returns_a_decided_price_to_undecided(priced):
    """A second reviewer traced a source the first could not, and turned a
    rejection into a hold. Since promotion stopped writing over decided rows,
    a revocation had no way back to the queue."""
    tool = _tool()
    tool.apply_decisions(priced, LINES, by="Christian Bartosch")
    held = [{**LINES[0], "decision": "HOLD", "reason": "verify the term"},
            {**LINES[2], "decision": "HOLD", "reason": "source traced"}]

    out = tool.apply_decisions(priced, held, by="Christian Bartosch")

    assert [o for _id, o, _d in out] == ["REOPENED", "REOPENED"]
    us, de = (_row(priced, i) for i in ("US-DIA-100-researched",
                                        "DE-DIA-500-researched"))
    assert not us.approved
    assert promotion.decision_on(us)["decision"] == "HELD"
    assert promotion.decision_on(de)["decision"] == "HELD"
    # The history stays in the note; the latest mark is the state.
    assert promotion.REVOKED_MARK in de.source_note
    assert promotion.HELD_MARK in de.source_note
    again = tool.apply_decisions(priced, held, by="Christian Bartosch")
    assert [o for _id, o, _d in again] == ["UNCHANGED", "UNCHANGED"]


def test_a_reason_that_would_read_as_a_decision_is_refused(priced):
    line = {**LINES[2], "reason": "was revoked by mistake"}
    with pytest.raises(promotion.NotPromotable, match="revoked by"):
        _tool().apply_decisions(priced, [line], by="Christian Bartosch")


def test_a_decision_is_not_applied_to_a_figure_nobody_decided(priced):
    """One row stands for a key across every company, and the next company's
    research can leave another figure in it. Approving whatever is there
    would approve a number nobody looked at."""
    line = {**LINES[0], "base": "625"}
    out = _tool().apply_decisions(priced, [line], by="Christian Bartosch")
    assert out[0][1] == "FIGURE_CHANGED"
    assert not _row(priced, "US-DIA-100-researched").approved


# ------------------------------------------------------ the committed register
def _register():
    path = ROOT / "samples" / "price_decisions.csv"
    if not path.exists():
        pytest.skip("no price_decisions.csv in this tree")
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_the_register_names_each_price_once_with_a_decision_it_can_apply():
    lines = _register()
    ids = [line["id"] for line in lines]
    assert len(ids) == len(set(ids)), "a price decided twice"
    for line in lines:
        assert line["decision"] in ("APPROVE", "REJECT", "HOLD"), line["id"]
        assert line["reason"].strip(), f"{line['id']} has no reason"
        assert line["id"].endswith("-researched"), line["id"]
        assert line["base"] and line["currency"], (
            f"{line['id']} does not say which figure was decided")
        if line["band_low"] or line["band_high"]:
            assert Decimal(line["band_low"]) < Decimal(line["band_high"]), (
                line["id"])


def test_a_hold_names_the_figure_it_holds(priced):
    """Like an approval or a rejection, a hold is about one figure. A row that
    now holds another is refused, not held."""
    line = {**LINES[3], "base": "149"}
    out = _tool().apply_decisions(priced, [line], by="Christian Bartosch")
    assert [o for _id, o, _d in out] == ["FIGURE_CHANGED"]
    assert promotion.decision_on(_row(priced, "ES-DIA-100-researched")) is None
