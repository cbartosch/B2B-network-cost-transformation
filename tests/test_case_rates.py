"""A client's own rates, which belong to that client and nobody else.

All eleven reference tables the estimate reads were global: two clients in the
same industry and country got the same rate card, the same lever bands and the
same serviceability, and only their footprints differed.

A client's invoices are the best evidence this model can have - a transaction
rather than a benchmark - and there was nowhere to put them. Loading them into
`reference.unit_cost_prior` would have priced every other engagement off one
client's negotiated deal, so the choice was between the best evidence available
and not contaminating the reference set, and it took the second by having no
third option.
"""
from decimal import Decimal as D

import pytest

from app.domain import case_rates


def _rate(**over):
    fields = dict(case_id="c", country="GB", service_class="IPVPN",
                  access_technology="ETHERNET_FIBRE", bandwidth_mbps=100,
                  monthly_recurring="980", currency="GBP", basis="INVOICE",
                  source="BT invoice 2026-03", circuit_count=1)
    fields.update(over)
    return case_rates.rate(**fields)


def test_an_invoice_is_the_only_thing_that_reaches_grade_a():
    """A transaction that happened, for this client, at this price. A quote is
    what a supplier says they would charge, and a baseline of quotes is a
    baseline of offers rather than of costs."""
    assert _rate(basis="INVOICE")["evidence_grade"] == "A"
    assert _rate(basis="CONTRACT")["evidence_grade"] == "A"
    assert _rate(basis="QUOTE")["evidence_grade"] == "B"
    assert _rate(basis="CLIENT_STATED", source=None)["evidence_grade"] == "C"


def test_an_invoice_with_no_source_is_refused():
    """The reason an invoice grades A is that somebody can go and look at it,
    and one nobody can find is a client-stated figure with a better label."""
    with pytest.raises(case_rates.RateRejected, match="go and look at it"):
        _rate(source="   ")


def test_a_zero_charge_is_an_absent_rate_not_a_free_circuit():
    """A baseline that counts it as nothing understates by exactly the amount
    nobody noticed."""
    with pytest.raises(case_rates.RateRejected, match="not a monthly charge"):
        _rate(monthly_recurring="0")
    with pytest.raises(case_rates.RateRejected):
        _rate(monthly_recurring="-500")


def test_an_unknown_basis_is_refused_because_the_grade_follows_from_it():
    with pytest.raises(case_rates.RateRejected, match="ungradeable"):
        _rate(basis="PROBABLY")


def test_the_index_takes_the_median_not_the_mean():
    """A retail estate has hundreds of circuits at one tier, and one mispriced
    line should not move the rate the whole tier prices at."""
    rows = [_rate(monthly_recurring=m)
            for m in ("980", "1020", "995", "9000", "1005")]
    indexed = case_rates.index(rows)
    key = ("GB", "IPVPN", "ETHERNET_FIBRE", 100)
    # median 1005/month = 12,060/year. A mean would give 31,200.
    assert indexed[key]["base"] == "12060"
    assert indexed[key]["rate_count"] == 5


def test_a_case_rate_is_a_point_not_an_invented_band():
    """An invoice is what was charged. Inventing a low and a high around it
    would manufacture uncertainty the evidence does not have."""
    prior = case_rates.as_prior(_rate())
    assert prior["low"] == prior["base"] == prior["high"]


def test_a_case_rate_does_not_expire():
    """A market benchmark goes stale; what a client paid does not. If the
    contract changes that is a new rate rather than an expired one."""
    assert case_rates.as_prior(_rate())["expires"] is None


def test_the_clients_own_rate_beats_the_market_card():
    """No amount of market evidence outranks the client's own bill."""
    from app.domain.estimate import match_prior

    market = {("GB", "MPLS", 100): {"base": "11760"}}
    client = case_rates.index([_rate(monthly_recurring="500")])
    hit, _ = match_prior(market, "GB", "MPLS", 100,
                         service_class="IPVPN",
                         access_technology="ETHERNET_FIBRE",
                         case_rates=client)
    assert hit["base"] == "6000", "the client's 500/month, not the market rate"
    assert hit["evidence_grade"] == "A"


def test_a_client_rate_with_no_bearer_still_prices():
    """The invoice said what they pay for an IPVPN at 100 Mbps and may not have
    said what carried it."""
    from app.domain.estimate import match_prior

    client = case_rates.index([_rate(access_technology=None)])
    hit, _ = match_prior({}, "GB", "MPLS", 100, service_class="IPVPN",
                         access_technology="VDSL", case_rates=client)
    assert hit is not None


def test_the_market_card_is_used_where_the_client_has_no_rate():
    """A case rate for one tier must not suppress the market rate for
    another."""
    from app.domain.estimate import match_prior

    market = {("GB", "MPLS", 1000): {"base": "24000"}}
    client = case_rates.index([_rate(bandwidth_mbps=100)])
    hit, _ = match_prior(market, "GB", "MPLS", 1000, service_class="IPVPN",
                         access_technology="ETHERNET_FIBRE",
                         case_rates=client)
    assert hit["base"] == "24000"


def test_the_rates_reconcile_against_the_clients_stated_spend():
    """The self-check a case rate makes possible and a market rate never
    could. On the reference estate this reconciles to the penny."""
    rows = [_rate(monthly_recurring="317679.29", circuit_count=2617)]
    exact = case_rates.leakage(rows, stated_total="3812151.48")
    assert exact["reconciles"] is True

    short = case_rates.leakage(rows, stated_total="4600000")
    assert short["reconciles"] is False
    assert "outside the perimeter" in short["note"]


def test_no_stated_spend_is_not_a_failed_reconciliation():
    out = case_rates.leakage([_rate()], stated_total=None)
    assert out["stated_total"] is None
    assert "reconciles" not in out


def test_a_markup_crosses_to_reference_and_the_charge_does_not():
    """A markup says something about the retail market; the charge underneath
    says what one company negotiated, and a second company's estimate built on
    it is a guess dressed as evidence."""
    out = case_rates.derived_markup(client_rate="980", wholesale_rate="620")
    assert out["crosses_to_reference"] is True
    assert D(out["markup_share"]) > 0
    assert "does not and stays on the case" in out["note"]


def test_buying_below_a_published_tariff_is_a_finding_not_an_error():
    """A large customer can buy below a published rate."""
    out = case_rates.derived_markup(client_rate="500", wholesale_rate="620")
    assert D(out["markup_share"]) < 0
    assert "buying power" in out["note"]


def test_case_rates_live_outside_the_reference_schema():
    """The schema is the boundary. Nothing here promotes to a prior."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "db.py").exists())
    db_source = (app / "db.py").read_text()
    start = db_source.index("case_rate = Table(")
    end = db_source.index(")", db_source.index("schema=", start))
    assert 'schema="outside_in"' in db_source[start:end]

    # and nothing writes a prior from a case rate
    api = (app / "routers" / "api.py").read_text()
    assert "insert(db.unit_cost_prior)" not in api


def test_the_coverage_gate_prices_what_the_calculation_prices():
    """Two different notions of "priced" would mean the gate measuring
    something the total does not contain."""
    import inspect

    from app.domain import coverage, estimate

    assert "case_rates" in inspect.signature(coverage.derive_scope).parameters
    assert "case_rates" in inspect.signature(
        estimate.build_components).parameters
