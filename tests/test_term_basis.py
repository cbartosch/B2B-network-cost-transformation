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
