"""CR-06: the reported band carries the estate's evidence.

The seeded price priors give every component a low/base/high, and that band
was the whole of an estimate's uncertainty. It is price dispersion and
nothing else: it does not know whether the site count was researched or
asserted, or whether the domains behind the estate were ever evidenced.

Across the twenty-company sample it produced low/base between 0.688 and
0.735 for every company - two researched domains or seventeen, 43 sites or
16,406 - because every one of them priced off the same card. The width was
real and said nothing about the company.
"""
import types

import pytest

from app.domain import estimate
from app.domain.money import D, Range
from app.domain.policy import PolicyInvalid, RangePolicy

POLICY = RangePolicy.from_rows({
    "widen_evidenced_public": "1.00", "widen_client_confirmed": "1.15",
    "widen_derived_public": "1.20", "widen_analyst_entered_scope": "1.35",
    "widen_benchmark_prior": "1.40", "widen_analyst_asserted_prior": "1.50",
    "widen_simulated": "1.55", "widen_unevidenced_domain_share": "0.50"})


def _c(key, qty_origin, cost_origin, base="1000"):
    return estimate.Component(
        key=key, layer="L0", driver="circuits", quantity=10,
        quantity_origin=qty_origin, unit_cost_origin=cost_origin,
        product="DIA", role="PRIMARY", service_class="DIA",
        access_technology="ETHERNET_FIBRE",
        value=Range(D(base) * D("0.7"), D(base), D(base) * D("1.4")))


def _factor(components, share=None):
    f, _ = estimate.evidence_widening(
        components, policy=POLICY, evidenced_domain_share=share)
    return f


# ------------------------------------------------- the fixed point of the scale

def test_a_fully_evidenced_estimate_keeps_the_rate_cards_band():
    """1.00 is the fixed point, not a floor somebody chose. An estimate whose
    quantity and price are both evidenced is reported at exactly the width
    the card gives it, and nothing is added."""
    comps = [_c("a", "EVIDENCED_PUBLIC", "EVIDENCED_PUBLIC")]
    assert _factor(comps, share=1) == D(1)
    out = estimate.current_tco(comps, range_factor=_factor(comps, share=1))
    assert out["total"]["low"] == "700.00"
    assert out["total"]["high"] == "1400.00"


def test_the_policy_refuses_a_moved_fixed_point():
    with pytest.raises(PolicyInvalid, match="fixed point"):
        RangePolicy.from_rows({**{k: str(v) for k, v in (
            ("widen_evidenced_public", "1.2"),
            ("widen_client_confirmed", "1.15"),
            ("widen_derived_public", "1.20"),
            ("widen_analyst_entered_scope", "1.35"),
            ("widen_benchmark_prior", "1.40"),
            ("widen_analyst_asserted_prior", "1.50"),
            ("widen_simulated", "1.55"),
            ("widen_unevidenced_domain_share", "0.50"))}})


# ----------------------------------------------------------- the base is fixed

def test_widening_never_moves_the_base():
    """Widening is a statement about uncertainty, not about the number. A
    version of this that moved the base would be re-forecasting under the
    name of honesty."""
    r = Range(D("700"), D("1000"), D("1400"))
    for f in ("1.0", "1.4", "3.0"):
        assert estimate.widen(r, f).base == D("1000")


def test_a_band_wide_enough_to_cross_zero_stops_at_zero():
    """A cost cannot be negative. A band that reaches zero is saying
    'possibly nothing', which is what zero means here."""
    r = Range(D("700"), D("1000"), D("1400"))
    assert estimate.widen(r, "10").low == D(0)


# ------------------------------------------------------ evidence changes width

def test_a_weakly_evidenced_estimate_is_reported_wider():
    """The acceptance criterion: range width varies with evidenced share."""
    strong = [_c("a", "EVIDENCED_PUBLIC", "EVIDENCED_PUBLIC")]
    weak = [_c("a", "SIMULATED", "BENCHMARK_PRIOR")]
    assert _factor(weak, share=1) > _factor(strong, share=1)


def test_the_weaker_of_the_two_origins_governs():
    """A perfectly evidenced site count priced off a benchmark is only as
    good as the benchmark."""
    mixed = [_c("a", "EVIDENCED_PUBLIC", "BENCHMARK_PRIOR")]
    both_bench = [_c("a", "BENCHMARK_PRIOR", "BENCHMARK_PRIOR")]
    assert _factor(mixed, share=1) == _factor(both_bench, share=1)


def test_unresearched_domains_widen_what_the_origins_cannot_see():
    """The price and the quantity may both be benchmark-solid while the
    estate they describe was never checked."""
    comps = [_c("a", "BENCHMARK_PRIOR", "BENCHMARK_PRIOR")]
    full = _factor(comps, share=1)
    half = _factor(comps, share=D("0.5"))
    none = _factor(comps, share=0)
    assert none > half > full


def test_two_of_seventeen_domains_is_clearly_wider_than_seventeen():
    """Stated in the CR's own terms. 2/17 against 17/17, same components."""
    comps = [_c("a", "ANALYST_ENTERED_SCOPE", "BENCHMARK_PRIOR")]
    thin = _factor(comps, share=D(2) / D(17))
    full = _factor(comps, share=D(1))
    assert thin / full > D("1.3"), (thin, full)


def test_the_factor_is_value_weighted_not_counted():
    """One large benchmark component and one tiny evidenced one is a
    benchmark estimate, however the components are counted."""
    comps = [_c("big", "BENCHMARK_PRIOR", "BENCHMARK_PRIOR", base="1000000"),
             _c("tiny", "EVIDENCED_PUBLIC", "EVIDENCED_PUBLIC", base="1")]
    assert _factor(comps, share=1) > D("1.39")


# -------------------------------------------------------------- the unexpected

def test_an_origin_nobody_mapped_takes_the_widest_multiplier():
    """Not 1.0. An unrecognised origin is one this policy has never been
    asked about, and treating it as evidenced would let a new origin silently
    narrow every band that used it."""
    assert POLICY.widen_for("SOMETHING_NEW") == POLICY.widen_for("SIMULATED")
    assert POLICY.widen_for(None) == POLICY.widen_for("SIMULATED")


def test_an_estimate_with_no_priced_value_is_not_widened():
    f, basis = estimate.evidence_widening([], policy=POLICY,
                                          evidenced_domain_share=0)
    assert f == D(1)
    assert "no priced value" in basis["note"]


# -------------------------------------------------------------- the explanation

def test_the_band_can_be_explained_rather_than_asserted():
    comps = [_c("a", "SIMULATED", "BENCHMARK_PRIOR")]
    _, basis = estimate.evidence_widening(
        comps, policy=POLICY, evidenced_domain_share=D("0.5"))
    assert basis["origin_factor"] and basis["coverage_factor"]
    assert basis["origin_mix"]["SIMULATED/BENCHMARK_PRIOR"] == "1.00"
    assert "rate card" in basis["basis"]
