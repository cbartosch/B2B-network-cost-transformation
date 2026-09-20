"""Exchange rates, as governed reference data.

A GBP case against a USD rate card refused to price: `currency.convert()` had
been written, tested and called by nothing, and `fx_convention` had sat on the
case since pre-flight read by no calculation. Refusing was correct while
nothing converted, and a dead end for any engagement not priced in dollars.

Reference data rather than a live feed on purpose. A rate a steward approved on
a date is reproducible: the same case re-run next week prices the same way, and
a run recorded in March can be explained in September.
"""
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.domain import currency


ROWS = [
    {"from_currency": "USD", "to_currency": "GBP", "rate": "0.79",
     "as_of": "2026-01-01", "convention": "BUDGET", "source": "client rate"},
    {"from_currency": "USD", "to_currency": "GBP", "rate": "0.7463",
     "as_of": "2026-09-16", "convention": "SPOT", "source": "mid-market"},
]


def test_the_declared_convention_is_used_when_it_exists():
    """The point of reading fx_convention at all. A budget rate is set once
    and held, so a baseline priced at it stays comparable to a plan priced at
    it; a spot rate makes the same estate cost a different amount on
    Tuesday."""
    chosen = currency.select_rate(ROWS, frm="USD", to="GBP",
                                  convention="BUDGET", as_of="2026-12-31")
    assert chosen["rate"] == D("0.79")
    assert chosen["convention"] == "BUDGET"
    assert chosen["exact"] is True


def test_another_convention_is_used_but_named():
    """A spot rate where a budget rate was asked for is a different claim
    about the year. Using it is better than refusing; using it silently is
    not."""
    chosen = currency.select_rate(ROWS, frm="USD", to="GBP",
                                  convention="AVERAGE", as_of="2026-12-31")
    assert chosen is not None
    assert chosen["exact"] is False
    assert "different claim about the year" in chosen["note"]


def test_a_rate_dated_after_the_pricing_date_is_flagged():
    """A rate from the wrong month beats no rate, and the reader has to be
    able to see which it was."""
    chosen = currency.select_rate(ROWS, frm="USD", to="GBP",
                                  convention="BUDGET", as_of="2025-01-01")
    assert chosen is not None and chosen["exact"] is False
    assert "dated after the pricing date" in chosen["note"]


def test_a_missing_pair_returns_none_so_the_caller_refuses():
    """No default of 1.0. A missing rate treated as parity is the error this
    module exists to prevent, and it would be invisible in the result."""
    assert currency.select_rate(ROWS, frm="USD", to="JPY",
                                convention="SPOT", as_of="2026-12-31") is None


def test_the_inverse_direction_is_found_and_marked():
    """One direction per pair is seeded; holding both invites them to
    disagree by a rounding."""
    chosen = currency.select_rate(ROWS, frm="GBP", to="USD",
                                  convention="SPOT", as_of="2026-12-31")
    assert chosen is not None and chosen["inverted"] is True


def test_a_row_naming_an_unpriceable_currency_is_skipped_not_fatal():
    """A bad row is something a steward fixes, not a reason to fail every
    estimate that loads the table."""
    rows = ROWS + [{"from_currency": "USD", "to_currency": "XXX",
                    "rate": "1", "as_of": "2026-01-01", "convention": "SPOT"}]
    chosen = currency.select_rate(rows, frm="USD", to="GBP",
                                  convention="SPOT", as_of="2026-12-31")
    assert chosen is not None and chosen["rate"] == D("0.7463")


@pytest.mark.parametrize("frm,to,amount,expected", [
    ("USD", "GBP", "1000", "746.30"),
    ("GBP", "USD", "1000", "1339.94"),
])
def test_the_arithmetic_runs_both_ways(frm, to, amount, expected):
    """A 1,000 dollar circuit is about 746 pounds; a 1,000 pound circuit is
    about 1,340 dollars. The inverse has to be derived, not assumed."""
    chosen = currency.select_rate(ROWS, frm=frm, to=to, convention="SPOT",
                                  as_of="2026-12-31")
    factor = (D("1") / chosen["rate"]) if chosen["inverted"] else chosen["rate"]
    assert abs(D(amount) * factor - D(expected)) < D("0.01")


# --------------------------------------------------- the seeded table
def test_every_priceable_currency_has_a_rate():
    """A currency the model will accept on a case and cannot convert is a
    case that refuses for a reason the analyst cannot act on."""
    from app.seed import FX_RATES

    covered = {row[1] for row in FX_RATES}
    missing = sorted(set(currency.KNOWN) - covered - {"USD"})
    assert not missing, missing


def test_the_seeded_rates_say_which_were_looked_up():
    """Two were sourced this month while correcting the GB rate card; the
    rest are indicative. That asymmetry is the honest state of it, and hiding
    it would make fourteen guesses look like evidence."""
    from app.seed import FX_RATES

    grades = {row[1]: row[5] for row in FX_RATES}
    assert grades["GBP"] == "B"
    assert grades["EUR"] == "B"
    assert grades["AED"] == "C", "a currency peg is better than a guess"
    assert grades["JPY"] == "E"


def test_an_indicative_rate_is_dated_a_year_not_a_day():
    """A figure nobody looked up should not wear a date that says somebody
    did."""
    from app.seed import FX_RATES

    for _f, to, _r, as_of, _c, grade, _s in FX_RATES:
        if grade == "E":
            assert as_of.endswith("-01-01"), (to, as_of)


def test_no_budget_rate_is_seeded():
    """A budget rate is what a client sets for their year, and this model has
    no client's budget rate. An engagement that has one adds it, and
    select_rate prefers it the moment it exists."""
    from app.seed import FX_RATES

    assert not [r for r in FX_RATES if r[4] == "BUDGET"]


# ------------------------------------------- the wiring, read from source
def _api():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    return (app / "routers" / "api.py").read_text()


def test_the_conversion_happens_once_before_anything_prices():
    """Converting at the point of use would mean every consumer carrying the
    rate, and one of them eventually not."""
    api = _api()
    conversion = api.index("if _fx is not None:")
    assert api.index("priors = {(r.country") < conversion
    assert api.index("sizing_priors = {") < conversion
    assert conversion < api.index("scope = coverage.derive_scope(")


def test_only_money_is_converted():
    """A bandwidth is not money and a price year is not money. Multiplying a
    field because it happens to be numeric is how a unit error gets in."""
    api = _api()
    block = api[api.index("if _fx is not None:"):][:1400]
    assert 'for _bound in ("low", "base", "high")' in block
    for never in ("bandwidth_mbps", "price_year", "expires"):
        assert f'_prior["{never}"] =' not in block


def test_a_missing_rate_still_refuses():
    """The behaviour that was right before any of this existed, and still
    is."""
    api = _api()
    assert "holds\\n                        f\"no rate for that pair" in api \
        or "no rate for that pair" in api
    assert "treated as parity would be invisible" in api


def test_the_conversion_is_pinned_for_reproducibility():
    """A rerun next week must use the same rate, or the same case gives a
    different answer for a reason nobody chose."""
    api = _api()
    assert '"fx": ({"from": _prior_ccy' in api
    for field in ("rate", "convention", "as_of", "evidence_grade"):
        assert f'"{field}":' in api[api.index('"fx": ({"from"'):][:700]
