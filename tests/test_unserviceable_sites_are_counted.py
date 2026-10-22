"""A site the simulation could not connect must count against coverage.

An unserviceable site produces no circuit, so it is absent from both the value
and the circuit tests - not unpriced, simply not there. 312 sites across nine
companies were removed this way, rural plants asking for an Ethernet bearer
the seed serviceability table marked undeliverable, and the estimates said
nothing. michelin had 58 of its 98 plants removed and reported COMPLETE, "all
coverage tests passed".

The serviceability table's own comment promised the opposite: "an estimate
that prices a circuit nobody can deliver is worse than one that reports it
cannot be delivered". This is where the report was supposed to happen.
"""
from decimal import Decimal as D

import pytest

from app.domain import coverage
from app.domain.policy import CoveragePolicy

POLICY = CoveragePolicy(
    set_name="test",
    prior_coverage_min=D("0.70"), prior_coverage_floor=D("0.40"),
    material_country_floor=D("0.10"), product_coverage_min=D("0.60"),
    prior_recency_annual_decay=D("0"), prior_recency_floor=D("0"))

# A single country, every circuit priced: COMPLETE on its own, so the only
# thing that can move its status in these tests is the unserviceable sites.
SCOPE = [{"country": "FR", "product": "ETHERNET", "count": 10,
          "annual_value": "100000", "priced": True, "rate_basis": "PRIOR",
          "evidence_grade": "E"}]


def _assess(dropped, simulated=40):
    rows = ([{"country": "FR", "archetype": "PLANT", "density": "RURAL",
              "sites": dropped, "asked_for": "ETHERNET",
              "reason": "no bearer that can carry a ETHERNET is available"}]
            if dropped else [])
    return coverage.assess(scope=SCOPE, layers_in_scope=["L0"],
                           layers_priced={"L0"}, policy=POLICY,
                           unserviceable=rows, simulated_sites=simulated)


def test_without_dropped_sites_nothing_changes():
    """The no-drop path must be byte-for-byte what it was."""
    cov = _assess(0)
    assert cov["status"] == "COMPLETE"
    assert cov["reason"] == "all coverage tests passed"
    assert cov["coverage_basis"] == "MIN_OF_VALUE_AND_CIRCUIT_COVERAGE"
    assert cov["unserviceable_sites"] == 0


def test_michelins_shape_is_not_complete():
    """58 dropped beside 40 simulated is 41% site coverage - above the 40%
    floor, below the 70% minimum. It said COMPLETE."""
    cov = _assess(58, simulated=40)
    assert cov["status"] == "PARTIAL"
    assert "58 site(s) the simulation could not connect" in cov["reason"]
    assert cov["site_coverage_pct"] == "0.408"
    assert cov["coverage_basis"] == "MIN_OF_VALUE_CIRCUIT_AND_SITE_COVERAGE"


def test_an_estate_mostly_missing_is_refused():
    """Below the absolute floor it is not an estimate - the same 40% rule
    that already refuses one priced on under two-fifths of its circuits."""
    cov = _assess(70, simulated=30)
    assert cov["status"] == "REFUSED"


def test_a_small_drop_is_complete_but_not_silent():
    """One site of five hundred passes every threshold. It is still missing,
    and "all coverage tests passed" on its own reads as nothing is."""
    cov = _assess(1, simulated=496)
    assert cov["status"] == "COMPLETE"
    assert cov["reason"].startswith("all coverage tests passed; ")
    assert "1 site(s) the simulation could not connect" in cov["reason"]


def test_the_dropped_sites_are_listed_for_a_reader():
    cov = _assess(26, simulated=51)
    assert cov["unserviceable_sites"] == 26
    assert cov["unserviceable"] == [{
        "country": "FR", "archetype": "PLANT", "density": "RURAL",
        "sites": 26, "asked_for": "ETHERNET",
        "reason": "no bearer that can carry a ETHERNET is available"}]


def test_site_coverage_joins_the_same_min_as_value_and_circuits():
    """No new threshold: the governed ones decide what a drop means."""
    cov = _assess(58, simulated=40)
    assert D(cov["effective_coverage_pct"]) == D(cov["site_coverage_pct"])
