"""The price review: from the card to a workbook a steward decides in, and back.

The first review of researched prices was a set of scratch scripts, run once
against a card where nothing was decided, and its decisions were carried
back into the register by hand. These cover the parts of the tools that
replaced them which do not need the database or a spreadsheet library.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------ review_prices
def test_a_cheaper_upper_tier_is_reported_as_an_inversion():
    """The estimate takes the cheapest tier at or above the need, so a cheap
    1 Gbps price under a dear 500 prices every circuit up to 1 Gbps."""
    inversions = _tool("review_prices").inversions_in(
        {100: 80, 500: 140, 1000: 59, 2000: 112})
    assert inversions == ["500 Mbps at 140 > 1000 Mbps at 59 USD"]


def test_a_tier_with_no_usd_figure_is_not_compared():
    assert _tool("review_prices").inversions_in({100: 80, 250: None, 500: 60})


@pytest.mark.parametrize("wording,flag", [
    ("Openreach EAD wholesale rental", "wholesale"),
    ("L2-BSA Vorleistungspreis", "wholesale"),
    ("cheapest consumer double-play, 20-36 EUR TTC", "consumer"),
    ("Leased lines start from around R8,000/mo", "floor"),
    ("1 Gbps symmetric from £195/month", "floor"),
    ("EUR 49.99 a month for 24 months. EUR 69.99 a month thereafter",
     "promotional"),
])
def test_wording_is_flagged_for_the_steward(wording, flag):
    flags = _tool("review_prices").flags_for(
        {"label": wording, "sources": [{"source_url": "a"},
                                       {"source_url": "b"}]},
        fx_error=None, inversions=[], untraceable=False)
    assert flag in flags, flags


def test_a_business_tariff_from_two_read_pages_raises_nothing():
    flags = _tool("review_prices").flags_for(
        {"label": "Virgin Media Business Voom 400, 24-month, ex VAT",
         "sources": [{"source_url": "a", "how_read": "FULL_PAGE"},
                     {"source_url": "b", "how_read": "FULL_PAGE"}]},
        fx_error=None, inversions=[], untraceable=False)
    assert flags == []


def test_what_the_card_cannot_do_is_flagged_too():
    flags = _tool("review_prices").flags_for(
        {"label": None, "sources": []}, fx_error="no NZD rate",
        inversions=["x"], untraceable=True)
    assert {"untraceable", "no exchange rate",
            "re-prices lower tiers", "single source"} <= set(flags)


# -------------------------------------------------------- build_price_review
def _row(**over):
    row = {"Price": "US-DIA-100-researched", "Decision": "Approve",
           "Researched price": 492, "Currency": "USD", "Band low": 333,
           "Band high": 641, "band_typed": True,
           "Reason": "  Lightyear median,\n 36-month  "}
    row.update(over)
    return row


def test_a_decided_row_becomes_the_line_the_register_holds():
    line = _tool("build_price_review").register_line(_row(), None)
    assert line == {"id": "US-DIA-100-researched", "decision": "APPROVE",
                    "base": "492.00", "currency": "USD", "band_low": "333",
                    "band_high": "641", "kind": "",
                    "reason": "Lightyear median, 36-month", "traced_url": ""}


def test_a_band_left_as_the_formula_is_the_cards_width():
    line = _tool("build_price_review").register_line(
        _row(band_typed=False, **{"Band low": 369.0}), None)
    assert line["band_low"] == "" and line["band_high"] == ""


def test_an_undecided_row_leaves_the_register_as_it_was():
    tool = _tool("build_price_review")
    register = {"US-DIA-100-researched": {"id": "US-DIA-100-researched",
                                          "decision": "HOLD"}}
    assert tool.rows_to_register([_row(Decision=None)], register) == register


def test_the_workbook_wins_and_keeps_the_kind_the_register_had():
    tool = _tool("build_price_review")
    register = {"US-DIA-100-researched": {
        "id": "US-DIA-100-researched", "decision": "HOLD",
        "kind": "MARKET_MEDIAN"}}
    merged = tool.rows_to_register([_row()], register)
    assert merged["US-DIA-100-researched"]["decision"] == "APPROVE"
    assert merged["US-DIA-100-researched"]["kind"] == "MARKET_MEDIAN"


def test_the_first_reviews_kind_column_reads_back_in_register_form():
    line = _tool("build_price_review").register_line(
        _row(Kind="business retail floor"), None)
    assert line["kind"] == "BUSINESS_RETAIL_FLOOR"


def test_a_decision_that_is_not_one_is_refused():
    with pytest.raises(ValueError, match="Maybe"):
        _tool("build_price_review").register_line(_row(Decision="Maybe"),
                                                  None)


# ----------------------------------------------- a source traced in review
def test_a_traced_source_makes_a_row_traceable():
    """Spain's DIA 600 stayed flagged untraceable after the audit opened
    Direct Telecom's page and read the figure on it, because research had
    stored only a run narrative. The register carries the page now."""
    tool = _tool("review_prices")
    narrative = {"from": "run narrative (the disposition was replaced)",
                 "label": None, "excerpt": None, "sources": []}
    evidence, untraceable = tool.traced(
        narrative, "https://direct-telecom.es/internet/business_class_fibre/")
    assert untraceable is False
    assert evidence["sources"][0]["how_read"] == "REVIEWER_TRACED"
    assert "untraceable" not in tool.flags_for(
        evidence, fx_error=None, inversions=[], untraceable=untraceable)


def test_a_traced_url_survives_the_workbook_round_trip():
    tool = _tool("build_price_review")
    previous = {"id": "US-DIA-100-researched",
                "traced_url": "https://example.com/tariff"}
    assert tool.register_line(_row(), previous)["traced_url"] == (
        "https://example.com/tariff")
    assert tool.register_line(
        _row(**{"Traced URL": "https://example.com/other"}),
        previous)["traced_url"] == "https://example.com/other"
