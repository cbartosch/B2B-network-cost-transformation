"""Two prices on different terms, brought onto one basis.

The model held `term_months`, `sla`, `taxes_included`, `equipment_included` and
`managed_services_included` on every prior and nothing read any of them - so a
benchmark on a 12-month term was compared against a 36-month rate card as
though the two were the same number, and a derived band's spread was partly a
spread of contract terms rather than of market price.
"""
from decimal import Decimal as D

import pytest

from app.domain import term_basis


def test_a_rate_already_on_the_reference_basis_is_untouched():
    """An adjustment that fires on every row is one nobody reads. Every seeded
    prior declares 36 months, so the common case adjusts nothing."""
    out = term_basis.normalise("1000", basis={"term_months": 36})
    assert out["normalised"] == "1000.00"
    assert out["adjusted"] is False
    assert out["grade_ceiling"] is None


def test_a_shorter_term_normalises_downward():
    """A 12-month price is higher per month than a 36-month one - the carrier
    recovers its install and its risk over fewer of them."""
    out = term_basis.normalise("1000", basis={"term_months": 12})
    assert D(out["normalised"]) < D("1000")
    assert out["steps"][0]["step"] == "term"


def test_a_longer_term_normalises_upward():
    out = term_basis.normalise("1000", basis={"term_months": 60})
    assert D(out["normalised"]) > D("1000")


def test_a_normalised_rate_can_never_be_better_than_grade_e():
    """The factor is market convention rather than measurement, so the result
    contains an assumption whatever the original was graded."""
    out = term_basis.normalise("1000", basis={"term_months": 12})
    assert out["grade_ceiling"] == "E"
    assert any("grade E" in w for w in out["warnings"])


def test_the_original_is_kept_beside_the_result():
    """A normalised rate that looks unnormalised is how an assumption becomes
    a fact - the same principle as the currency conversion."""
    out = term_basis.normalise("1000", basis={"term_months": 12})
    assert out["original"] == "1000"
    assert out["normalised"] != out["original"]
    assert out["steps"][0]["why"]


def test_an_included_component_is_removed_to_compare_like_with_like():
    bare = term_basis.normalise("1000", basis={"term_months": 36})
    with_kit = term_basis.normalise(
        "1000", basis={"term_months": 36, "equipment_included": True})
    assert D(with_kit["normalised"]) < D(bare["normalised"])


def test_an_undeclared_term_is_interpolated_not_refused():
    """A 30-month contract is a real contract, and rejecting it would push an
    analyst to mislabel it as 24 or 36."""
    out = term_basis.normalise("1000", basis={"term_months": 30})
    assert out["adjusted"] is True
    factor = term_basis.term_factor(30)
    assert term_basis.TERM_FACTORS[36] < factor < term_basis.TERM_FACTORS[24]


def test_a_term_outside_the_convention_is_clamped_not_extrapolated():
    """A 120-month price is a different kind of deal, and projecting the curve
    to it would invent a discount nobody offers."""
    assert term_basis.term_factor(120) == term_basis.TERM_FACTORS[60]
    assert term_basis.term_factor(1) == term_basis.TERM_FACTORS[1]


def test_a_tax_inclusive_rate_is_reported_not_adjusted():
    """The model has no tax table, and inventing a rate would be worse than
    naming the gap."""
    out = term_basis.normalise(
        "1000", basis={"term_months": 36, "taxes_included": True})
    assert out["normalised"] == "1000.00"
    assert any("no tax table" in w for w in out["warnings"])


def test_a_missing_term_warns_rather_than_assuming_the_reference():
    out = term_basis.normalise("1000", basis={})
    assert any("no term is declared" in w for w in out["warnings"])


def test_an_sla_difference_cannot_be_normalised_away():
    """A premium SLA is a different service rather than the same one priced
    differently."""
    out = term_basis.comparable(
        {"term_months": 36, "sla": "STANDARD_BUSINESS"},
        {"term_months": 36, "sla": "PREMIUM"})
    assert out["same_basis"] is False
    assert "sla" in out["differences"]
    assert "different service" in out["note"]


def test_bands_are_derived_from_normalised_observations():
    """Observations of a 12-month and a 36-month price were pooled as though
    they were the same number, so a band's spread was partly a spread of
    contract terms."""
    import inspect

    from app.domain import benchmark_ingest

    source = inspect.getsource(benchmark_ingest.derive_bands)
    assert "term_basis.normalise(" in source
    assert "values = sorted(normalised)" in source


def test_the_derived_prior_records_that_it_was_normalised():
    """An adjustment nobody can see is an assumption that became a fact."""
    import inspect

    from app.domain import benchmark_ingest

    source = inspect.getsource(benchmark_ingest.derive_bands)
    assert "basis_warnings" in source
    assert "already on the reference" in source


# ------------------- a factor measured from the market beats the convention
def _obs(country="GB", vendor="BT", service="IPVPN", mbps=100,
         term=36, value="1000"):
    return {"country": country, "vendor": vendor, "service_class": service,
            "bandwidth_mbps": mbps, "term_months": term, "value": value}


def test_a_pair_differing_only_by_term_measures_the_factor():
    """Where the same circuit from the same vendor is observed on two terms,
    that pair is evidence about the factor - and the convention would rather
    trust itself than the two quotes in front of it."""
    out = term_basis.observed_factors([
        _obs(term=36, value="1000"), _obs(term=12, value="1220")])
    # 1220/1000. The first version of this test asserted 1.2100 - a number I
    # arrived at by eye rather than by division, which is the failure mode the
    # whole module exists to prevent one level down.
    assert out["factors"][12] == "1.2200"
    assert out["factors"][12] != str(term_basis.TERM_FACTORS[12])


def test_a_pair_differing_by_more_than_term_measures_nothing():
    """Same country and term but a different vendor is two circuits, not one
    circuit on two terms, and the ratio between them measures nothing."""
    out = term_basis.observed_factors([
        _obs(vendor="BT", term=36, value="1000"),
        _obs(vendor="Colt", term=12, value="1220")])
    assert out["factors"] == {}
    assert "no pair differing only by term" in out["note"]


def test_a_group_with_no_reference_term_is_skipped():
    """A ratio has nothing to be a ratio *to*. Chaining through an
    intermediate term would compound two measurements."""
    out = term_basis.observed_factors([
        _obs(term=12, value="1220"), _obs(term=24, value="1100")])
    assert out["factors"] == {}


def test_the_measured_factor_is_a_median_not_a_mean():
    """One mispriced quote should not move the curve."""
    out = term_basis.observed_factors([
        _obs(mbps=100, term=36, value="1000"),
        _obs(mbps=100, term=12, value="1100"),
        _obs(mbps=200, term=36, value="1000"),
        _obs(mbps=200, term=12, value="1200"),
        _obs(mbps=300, term=36, value="1000"),
        _obs(mbps=300, term=12, value="9000"),   # a bad quote
    ])
    # median of 1.1, 1.2, 9.0 is 1.2 - a mean would be 3.77
    assert out["factors"][12] == "1.2000"


def test_a_measured_factor_is_preferred_and_grades_higher():
    """It is a measurement, which is exactly why it is preferred - so it does
    not cap the result at E the way the convention does."""
    measured = term_basis.observed_factors([
        _obs(term=36, value="1000"), _obs(term=12, value="1220")])["factors"]
    assert measured[12] == "1.2200"
    convention = term_basis.normalise("1220", basis={"term_months": 12})
    observed = term_basis.normalise("1220", basis={"term_months": 12},
                                    measured=measured)
    assert convention["factor_source"] == "CONVENTION"
    assert observed["factor_source"] == "MEASURED"
    assert convention["grade_ceiling"] == "E"
    assert observed["grade_ceiling"] == "C"
    assert D(observed["normalised"]) < D(convention["normalised"])


def test_an_inclusion_adjustment_still_caps_at_e():
    """Those factors remain convention even when the term factor was
    measured."""
    measured = {12: "1.21"}
    out = term_basis.normalise(
        "1220", basis={"term_months": 12, "equipment_included": True},
        measured=measured)
    assert out["grade_ceiling"] == "E"


def test_with_no_measurement_the_convention_stands_unchanged():
    """The refinement must not change the answer where there is nothing to
    measure from."""
    plain = term_basis.normalise("1220", basis={"term_months": 12})
    empty = term_basis.normalise("1220", basis={"term_months": 12},
                                 measured={})
    assert plain["normalised"] == empty["normalised"]


def test_band_derivation_measures_before_it_normalises():
    """Measuring after normalising would measure the convention it just
    applied."""
    import ast
    import inspect

    from app.domain import benchmark_ingest

    source = ast.unparse(ast.parse(
        inspect.getsource(benchmark_ingest.derive_bands)))
    assert source.index("observed_factors") < source.index(
        "term_basis.normalise")
