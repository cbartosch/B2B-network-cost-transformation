"""Triangulation: several sources' figures into one band, deterministically.

The motivating case is real. HypoVereinsbank's German branch count appears as
341 in a restructuring record, around 400 in a contemporaneous newspaper
projection, and 371 in a later NGO profile. The schema had one `value` field,
so the agent had to pick one and discard the other two - and picking is the
opposite of triangulating.
"""
import types
from decimal import Decimal as D

import pytest

from app.domain import triangulate as T
from app.domain.policy import PolicyInvalid, TriangulationPolicy


def _policy(spread="0.15", stale=3):
    return TriangulationPolicy(set_name="t", material_spread_share=D(spread),
                               stale_after_years=stale)


UNICREDIT = [{
    "label": "STORE", "country": "DE", "unit": "sites", "value": 371,
    "candidates": [
        {"value": 341, "as_of": "2021", "publisher": "restructuring record"},
        {"value": 400, "as_of": "2021", "publisher": "press projection"},
        {"value": 371, "as_of": "2023", "publisher": "NGO profile"}]}]


def test_three_disagreeing_sources_become_a_band_not_a_choice():
    t = T.triangulate(UNICREDIT, policy=_policy(), price_year=2026)[0]
    assert (t["low"], t["base"], t["high"]) == (341, 371, 400)
    assert t["candidate_count"] == 3
    assert t["oldest_year"] == 2021 and t["newest_year"] == 2023


def test_a_material_spread_is_flagged_and_queued_not_averaged_away():
    t = T.triangulate(UNICREDIT, policy=_policy(), price_year=2026)[0]
    assert T.MATERIAL_SPREAD in t["flags"]
    assert t["review_required"] and t["conflict_group_id"]

    queue = T.review_queue([t])
    assert len(queue) == 1
    assert "disagreement is the finding" in queue[0]["why"]
    assert len(queue[0]["candidates"]) == 3, (
        "the candidates must survive into review - a conflict nobody can see "
        "has not been retained")


def test_the_base_is_the_median_so_one_outlier_cannot_move_it():
    """The mean of 341, 371 and 4000 is 1571, which is not a branch count."""
    with_outlier = [{**UNICREDIT[0], "candidates": [
        {"value": 341, "as_of": "2021"}, {"value": 371, "as_of": "2023"},
        {"value": 4000, "as_of": "2022"}]}]
    t = T.triangulate(with_outlier, policy=_policy(), price_year=2026)[0]
    assert t["base"] == 371


def test_a_single_source_is_labelled_as_one():
    t = T.triangulate([{"label": "DC", "country": "DE", "unit": "sites",
                        "value": 1}], policy=_policy(), price_year=2026)[0]
    assert T.SINGLE_SOURCE in t["flags"]
    assert (t["low"], t["base"], t["high"]) == (1, 1, 1)
    assert not t["review_required"], (
        "one source is thin, not contradictory - flagging it for review would "
        "fill the queue with everything and get the queue ignored")


def test_a_stale_band_is_flagged_against_the_price_year():
    t = T.triangulate([{"label": "STORE", "country": "DE", "unit": "sites",
                        "value": 580, "as_of": "2018"}],
                      policy=_policy(stale=3), price_year=2026)[0]
    assert T.STALE in t["flags"]


def test_a_newest_source_far_from_the_median_is_reported_not_preferred():
    """A shrinking estate and a wrong outlier are indistinguishable from
    inside the arithmetic. Only a person can tell them apart, so the
    divergence is surfaced rather than silently resolved."""
    shrinking = [{"label": "STORE", "country": "DE", "unit": "sites",
                  "value": 300, "candidates": [
                      {"value": 580, "as_of": "2019"},
                      {"value": 500, "as_of": "2020"},
                      {"value": 300, "as_of": "2025"}]}]
    t = T.triangulate(shrinking, policy=_policy(), price_year=2026)[0]
    assert T.NEWEST_DIVERGES in t["flags"]
    assert t["base"] == 500, "the median is reported, not the newest"
    assert t["newest_value"] == 300
    assert "trend or an outlier" in T.review_queue([t])[0]["why"]


def test_candidates_in_different_units_are_not_banded_together():
    """Different units are not a disagreement about a number, they are a
    disagreement about what is being counted."""
    mixed = [{"label": "STORE", "country": "DE", "unit": "sites",
              "value": 371, "candidates": [
                  {"value": 371, "unit": "sites", "as_of": "2023"},
                  {"value": 9052, "unit": "employees", "as_of": "2024"}]}]
    t = T.triangulate(mixed, policy=_policy(), price_year=2026)[0]
    assert T.UNIT_MISMATCH in t["flags"] and t["review_required"]
    assert len(t["set_aside"]) == 1


def test_findings_about_the_same_thing_merge_across_quantities():
    """Corroboration across sources is what makes a band mean anything, so
    two separate quantities for the same label and country are one group."""
    split = [
        {"label": "STORE", "country": "DE", "unit": "sites", "value": 341,
         "as_of": "2021"},
        {"label": "STORE", "country": "DE", "unit": "sites", "value": 400,
         "as_of": "2021"},
    ]
    out = T.triangulate(split, policy=_policy(), price_year=2026)
    assert len(out) == 1 and out[0]["candidate_count"] == 2


def test_a_zero_spread_threshold_is_refused():
    with pytest.raises(PolicyInvalid, match="read by nobody"):
        _policy(spread="0").validate()


def test_an_unparseable_candidate_is_set_aside_not_dropped():
    """Dropping it silently is how a two-source band becomes a one-source band
    that still looks corroborated."""
    t = T.triangulate([{"label": "STORE", "country": "DE", "unit": "sites",
                        "value": 371, "candidates": [
                            {"value": 371, "as_of": "2023"},
                            {"value": "about four hundred", "as_of": "2021"}]}],
                      policy=_policy(), price_year=2026)[0]
    assert t["candidate_count"] == 1
    assert len(t["set_aside"]) == 1
    assert T.SINGLE_SOURCE in t["flags"]
