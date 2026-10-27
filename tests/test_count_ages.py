"""A site count says when it was true, and the estimate now reads it.

A price carries `expires`, and coverage.expired_price_share reports how much
of the baseline rests on a rate past it. A site count carries `as_of` and
nothing read it: a count from 2002 entered the estate weighted exactly like
one from this year, and only the footprint check, outside the estimate,
reported the difference.
"""
from app.domain import coverage

ESTATE = [{"country": "DE", "archetype": "DC", "sites": 1},
          {"country": "FR", "archetype": "PLANT", "sites": 28},
          {"country": "FR", "archetype": "OFFICE", "sites": 12},
          {"country": "GB", "archetype": "STORE", "sites": 59}]


def test_an_old_research_count_in_the_estate_is_reported():
    """Nestle's German DC entered on a 2002 finding."""
    out = coverage.count_ages(
        [{"country": "DE", "archetype": "DC", "sites": 1,
          "as_of": "2002 (IBM-era regional DC)"},
         {"country": "GB", "archetype": "STORE", "sites": 59,
          "as_of": "FY2025"}],
        ESTATE, as_of_year=2026)
    assert [(c["country"], c["age"]) for c in out["stale_counts"]] == [
        ("DE", 24)]
    assert out["stale_count_share"] == "0.010"


def test_a_count_with_no_date_is_listed_apart():
    out = coverage.count_ages(
        [{"country": "FR", "archetype": "OFFICE", "sites": 12,
          "as_of": None}], ESTATE, as_of_year=2026)
    assert out["undated_counts"][0]["archetype"] == "OFFICE"
    assert out["stale_count_share"] == "0.000"


def test_a_lower_finding_is_evidence_about_the_estate_not_part_of_it():
    """Research supersedes a declaration only with a count at least as
    large: 13 French plants against a declared 28 never reached it."""
    out = coverage.count_ages(
        [{"country": "FR", "archetype": "PLANT", "sites": 13,
          "as_of": "2019"}], ESTATE, as_of_year=2026)
    assert out["stale_counts"] == [] and out["undated_counts"] == []
