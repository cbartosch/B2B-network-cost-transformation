"""Pricing from a rate card that holds more than one currency.

The card was single-currency for as long as every row in it was seeded, and
`assert_single_currency` refused a mix - rightly, because a mix could only
mean a mistake: a USD card priced against a GBP anchor.

A promoted price is stored in the currency its source quoted, deliberately,
because stamping every promoted price USD once put a EUR tariff into the
card as dollars. So approving one makes the card legitimately mixed, and the
refusal started blocking 11 of 26 companies on two approved EUR rows.
"""
from decimal import Decimal

import pytest

from app.domain import currency


FX = [
    {"from_currency": "USD", "to_currency": "EUR", "rate": "0.871",
     "as_of": "2026-01-01", "convention": "SPOT", "source": "seed",
     "evidence_grade": "E"},
    {"from_currency": "USD", "to_currency": "GBP", "rate": "0.746",
     "as_of": "2026-01-01", "convention": "SPOT", "source": "seed",
     "evidence_grade": "E"},
]


def _table(currencies, to="USD"):
    return currency.rate_table(FX, currencies=currencies, to=to,
                               convention="SPOT",
                               as_of="2026-12-31")["factors"]


# ------------------------------------------------------- the conversion

def test_the_case_currency_converts_at_one():
    assert _table(["USD"])["USD"] == Decimal(1)


def test_each_currency_gets_its_own_factor():
    """One factor for the card was the bug: it assumed every row shared a
    currency, so there was nothing to apply per row."""
    table = _table(["USD", "EUR", "GBP"])
    assert set(table) == {"USD", "EUR", "GBP"}
    assert table["EUR"] != table["GBP"]


def test_an_inverted_pair_is_handled():
    """fx_rate stores USD->EUR and the card holds EUR, so the factor to get
    back to USD is the reciprocal."""
    table = _table(["EUR"])
    assert table["EUR"] == pytest.approx(Decimal(1) / Decimal("0.871"), rel=1e-6)


def test_a_card_of_one_currency_still_works():
    """The single-currency path must behave exactly as before, or this
    change reprices every estimate that was already right."""
    table = _table(["USD", "USD", "USD"])
    assert table == {"USD": Decimal(1)}


def test_a_blank_currency_is_ignored_rather_than_guessed():
    table = _table(["USD", None, ""])
    assert table == {"USD": Decimal(1)}


# ---------------------------------------------------------- the refusal

def test_a_missing_rate_is_refused_not_assumed():
    """A missing rate treated as parity would be invisible in the result."""
    with pytest.raises(currency.CurrencyMismatch) as e:
        _table(["USD", "JPY"])
    assert "JPY" in str(e.value)


def test_every_missing_currency_is_named_not_the_first():
    """A steward adding rates wants the list, not one at a time."""
    with pytest.raises(currency.CurrencyMismatch) as e:
        _table(["USD", "JPY", "BRL"])
    msg = str(e.value)
    assert "BRL" in msg and "JPY" in msg


def test_the_refusal_names_the_way_out():
    with pytest.raises(currency.CurrencyMismatch) as e:
        _table(["USD", "JPY"])
    assert "revoked" in str(e.value) or "adds the rate" in str(e.value)


# -------------------------------------------- the control it replaces

def test_assert_single_currency_still_exists_for_its_own_case():
    """It was not wrong, it was outgrown. A set of figures that should
    share a currency and does not is still a mistake worth refusing."""
    with pytest.raises(currency.CurrencyMismatch):
        currency.assert_single_currency(
            [{"currency": "USD"}, {"currency": "EUR"}])


# ------------------------------------------- crossing through the pivot

CHF_FX = FX + [{"from_currency": "USD", "to_currency": "CHF",
                "rate": "0.905", "as_of": "2026-01-01", "convention": "SPOT",
                "source": "seed", "evidence_grade": "E"}]


def _chf(currencies):
    return currency.rate_table(CHF_FX, currencies=currencies, to="CHF",
                               convention="SPOT", as_of="2026-12-31")


def test_a_pair_the_table_does_not_hold_is_crossed_through_its_pivot():
    """reference.fx_rate is a star - every row is USD -> X - so EUR to CHF
    is not a pair it holds and never will be. Refusing it means the card
    can only ever be USD or the case's own currency, which is the same
    blockage in a new shape: it stopped Novartis and Nestle pricing at all.
    """
    out = _chf(["EUR"])
    assert out["factors"]["EUR"] == (
        Decimal(1) / Decimal("0.871") * Decimal("0.905"))


def test_a_direct_pair_is_preferred_to_a_cross():
    """Crossing compounds two rates. Where one will do, one is used."""
    out = _chf(["USD"])
    assert out["factors"]["USD"] == Decimal("0.905")
    assert out["detail"]["USD"]["via"] is None


def test_a_crossed_rate_records_both_legs():
    """A figure that crossed two indicative rates is weaker than one that
    crossed one, and the result has to say so."""
    legs = _chf(["EUR"])["detail"]["EUR"]
    assert legs["via"] == "USD"
    assert [(x["from"], x["to"]) for x in legs["legs"]] == [("EUR", "USD"),
                                                            ("USD", "CHF")]
    assert "crossed two indicative rates" in legs["note"]


def test_a_crossed_rate_takes_the_weaker_grade():
    """A chain is as good as its worst link; reporting the better one would
    overstate it."""
    rows = [dict(r) for r in CHF_FX]
    rows[0]["evidence_grade"] = "C"          # USD->EUR is sourced
    out = currency.rate_table(rows, currencies=["EUR"], to="CHF",
                              convention="SPOT", as_of="2026-12-31")
    assert out["detail"]["EUR"]["evidence_grade"] == "E"


def test_the_pivot_is_read_off_the_table_not_assumed():
    """Hardcoding USD would be right today and silently wrong the first
    time somebody seeds a EUR-centred table."""
    rows = [{"from_currency": "EUR", "to_currency": c, "rate": "2",
             "as_of": "2026-01-01", "convention": "SPOT", "source": "seed",
             "evidence_grade": "E"} for c in ("USD", "GBP", "CHF")]
    assert currency._pivot_currency(rows) == "EUR"
    out = currency.rate_table(rows, currencies=["GBP"], to="CHF",
                              convention="SPOT", as_of="2026-12-31")
    assert out["detail"]["GBP"]["via"] == "EUR"


def test_a_currency_the_pivot_cannot_reach_is_still_refused():
    with pytest.raises(currency.CurrencyMismatch) as e:
        _chf(["JPY"])
    assert "JPY" in str(e.value)
