"""Money in one currency, or an explicit conversion that says so.

Every seeded prior is USD. The anchor carried no currency at all, so a GBP
disclosure entered against a USD rate card was arithmetic on mixed units - a
21.3% understatement - and the snapshot then labelled the result with the
case's base currency, asserting a currency the calculation never established.

`fx_convention` was collected, required by pre-flight, and read by nothing.
"""
from decimal import Decimal as D

import pytest

from app.domain import currency

RATES = {("GBP", "USD"): D("1.27"), ("EUR", "USD"): D("1.08")}


def test_the_reported_case_is_now_a_conversion_with_its_arithmetic():
    """EUR 213,000,000 read as USD understated by 7.4%; GBP by 21.3%."""
    out = currency.convert(D("213000000"), frm="GBP", to="USD", rates=RATES)
    assert out["converted"] is True
    assert out["amount"] == D("213000000") * D("1.27")
    assert "1.27" in out["note"]


def test_the_same_currency_converts_nothing():
    """The common case. A GB engagement against GB priors converts nothing, and
    the machinery must not make that look like work."""
    out = currency.convert(100, frm="GBP", to="GBP", rates={})
    assert out["converted"] is False
    assert out["rate"] == D("1")


def test_a_missing_rate_is_refused_rather_than_assumed():
    """There is no default of 1.0. Treating an unknown rate as parity is
    exactly the error this exists to prevent, and it would be invisible in the
    result."""
    with pytest.raises(currency.CurrencyMismatch, match="Refused rather than"):
        currency.convert(1, frm="JPY", to="USD", rates=RATES)


def test_an_inverse_is_derived_rather_than_stored_twice():
    """Holding both directions invites them to disagree."""
    out = currency.convert(100, frm="USD", to="GBP", rates=RATES)
    assert out["inverted"] is True
    assert out["amount"] == D("100") / D("1.27")


def test_a_currency_the_model_cannot_price_is_refused_by_name():
    with pytest.raises(currency.UnknownCurrency):
        currency.normalise("POUNDS")
    assert currency.normalise("gbp") == "GBP"
    assert currency.normalise(None) is None


def test_mixed_rows_are_refused_rather_than_summed():
    """The cheapest control and the one that catches the real case: a rate card
    seeded entirely in USD priced against a GBP anchor."""
    with pytest.raises(currency.CurrencyMismatch, match="no conversion"):
        currency.assert_single_currency(
            [{"currency": "USD"}, {"currency": "GBP"}])
    assert currency.assert_single_currency(
        [{"currency": "USD"}, {"currency": "USD"}]) == "USD"


def test_a_partial_reconciliation_says_it_is_partial():
    """A total assembled from three of five figures is not a total, and
    reporting it beside the two it could not convert would invite it to be read
    as one."""
    out = currency.reconcile(
        [{"amount": 100, "currency": "GBP"}, {"amount": 50, "currency": "JPY"}],
        to="USD", rates=RATES)
    assert out["complete"] is False
    assert len(out["unconvertible"]) == 1
    assert "only part of the input" in out["note"]


def test_the_estimate_refuses_a_rate_card_in_another_currency():
    """Refused rather than converted: at V0 every rate is an expert
    assumption, and applying an exchange rate to one adds a second unevidenced
    step to an unevidenced number."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "currency.assert_single_currency" in api
    assert "currencies do not reconcile" in api


def test_the_anchor_carries_its_own_currency():
    """It carried none, so a GBP disclosure against a USD rate card was
    arithmetic on mixed units."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    assert "anchor_currency" in (app / "routers" / "api.py").read_text()


# ------------------------------------------------- a rate has a shelf life
@pytest.mark.parametrize("expires,as_of,expired", [
    ("2026-12-31", "2027-01-01", True),
    ("2026-12-31", "2026-06-01", False),
    # The boundary. A rate expires at the end of the day it names, so the day
    # itself is still current - and a governed date compared with < rather than
    # <= is the difference between a card working and failing on 31 December.
    ("2026-12-31", "2026-12-31", False),
    (None, "2030-01-01", False),
    ("2020-01-01", None, False),
    ("soon", "2027-01-01", False),
])
def test_a_rate_expires_when_it_says_it_does(expires, as_of, expired):
    """Every seeded prior carries `expires` and nothing read it, so on 1
    January the whole card goes stale and prices silently - the same shape as
    `fx_convention` collected and never consulted.

    A missing expiry is not an expiry: a prior that never declared a shelf life
    cannot have passed it, and treating silence as expired would retire every
    rate an analyst entered by hand. A malformed one compares as current rather
    than raising in the middle of a price lookup."""
    from app.domain.estimate import is_expired

    prior = {"expires": expires} if expires is not None else {}
    assert is_expired(prior, as_of=as_of) is expired


def test_an_expired_rate_still_prices_and_is_reported():
    """Refusing would trade a stale number for unpriced scope, which reads as
    "we do not know" when the truth is "we knew, a while ago". An expired price
    is worse evidence than a current one and better evidence than none."""
    import inspect

    from app.domain import coverage

    source = inspect.getsource(coverage.derive_scope)
    assert '"prior_expired"' in source
    assert '"priced": prior is not None' in source, (
        "an expired prior must still count as priced")


def test_the_expired_share_is_value_weighted():
    """Ten stale rates on small sites and one on the whole estate are
    different findings."""
    import inspect

    from app.domain import coverage

    source = inspect.getsource(coverage.assess)
    assert "expired_price_share" in source
    assert 'annual_value' in source


def test_the_as_of_date_is_pinned_to_the_case_not_to_today():
    """An estimate must reproduce. "Expired" measured against a moving today
    would make the same run give different answers on different days."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert 'as_of=f"{case_row.price_year' in api


def test_both_evidence_shares_reach_a_screen():
    """Both controls existed and neither was on a page, so an estimate priced
    entirely from expired seeded assumptions looked identical to one priced
    from current cleared benchmarks."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(p for p in (root / "analyst_ui").rglob("*.py")
                if "Run_V0" in p.name).read_text()
    assert "unsourced_price_share" in page
    assert "expired_price_share" in page
