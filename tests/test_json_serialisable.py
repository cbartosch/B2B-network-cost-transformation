"""Nothing written to a JSON column may contain a Decimal.

json.dumps cannot serialise a Decimal, and Postgres JSON columns go through it.
So a Decimal in a stored dict is a TypeError at the moment of writing - after
the provider call, the search and the source fetches have all succeeded. Two
domains died this way with "Object of type Decimal is not JSON serializable"
while the research behind them had worked.

It cannot be caught by compiling or by reading: only the write fails, and only
for the shapes that happen to contain one. So the shapes are checked here.
"""
import json
import types
from decimal import Decimal as D

import pytest

from app.domain import reliability, triangulate


def _policy(spread="0.15", stale=3, minimum=2):
    return types.SimpleNamespace(
        material_spread_share=D(spread), stale_after_years=stale,
        min_independent_sources_material_fact=minimum)


def _assert_json(payload, what):
    try:
        json.dumps(payload)
    except TypeError as exc:
        pytest.fail(f"{what} cannot be stored in a JSON column: {exc}")


@pytest.mark.parametrize("candidates,label", [
    (["341", "400", "371"], "site counts"),
    (["477.50", "520.25", "609.00"], "prices"),
    (["1"], "a single source"),
    (["2 halls, 2.75 MW"], "prose only"),
])
def test_a_triangulated_band_is_storable(candidates, label):
    out = triangulate.triangulate(
        [{"label": label, "country": "DE", "unit": "x",
          "value": candidates[0],
          "candidates": [{"value": c, "as_of": "2024"} for c in candidates]}],
        policy=_policy(), price_year=2026)
    _assert_json(out, f"a band of {label}")


def test_a_band_keeps_the_number_it_was_given():
    """money.as_str would render a site count as "341.00" - money formatting
    applied to something that is not money."""
    out = triangulate.triangulate(
        [{"label": "STORE", "country": "DE", "unit": "sites", "value": "341",
          "candidates": [{"value": v, "as_of": "2024"}
                         for v in ("341", "400", "371")]}],
        policy=_policy(), price_year=2026)[0]
    assert (out["low"], out["base"], out["high"]) == ("341", "371", "400")

    prices = triangulate.triangulate(
        [{"label": "DIA", "country": "US", "unit": "USD", "value": "477.50",
          "candidates": [{"value": v, "as_of": "2024"}
                         for v in ("477.50", "520.25", "609.00")]}],
        policy=_policy(), price_year=2026)[0]
    assert prices["base"] == "520.25", "a price must not lose its decimals"


def test_the_review_queue_is_storable():
    out = triangulate.triangulate(
        [{"label": "STORE", "country": "DE", "unit": "sites", "value": "341",
          "candidates": [{"value": v, "as_of": "2021"}
                         for v in ("341", "400")]}],
        policy=_policy(), price_year=2026)
    _assert_json(triangulate.review_queue(out), "the conflict review queue")


def test_a_reliability_grade_is_storable():
    graded = reliability.grade(
        verified_sources=[{"publisher": "AR", "source_class": "PRIMARY_FILING",
                           "how_read": "FULL_PAGE", "figure_basis": "STATED"}],
        claimed_sources=2,
        band=triangulate.triangulate(
            [{"label": "STORE", "country": "DE", "unit": "sites",
              "value": "341",
              "candidates": [{"value": v, "as_of": "2024"}
                             for v in ("341", "371")]}],
            policy=_policy(), price_year=2026)[0],
        policy=_policy(), price_year=2026)
    _assert_json(graded, "a reliability grade")


def test_no_json_column_default_is_a_decimal():
    """A guard on the whole class rather than the instances: any model column
    typed JSON must not be handed a Decimal by a default either."""
    from app import db
    offenders = []
    for table in db.metadata.sorted_tables:
        for column in table.columns:
            if column.type.__class__.__name__ != "JSON":
                continue
            default = getattr(column.default, "arg", None)
            if isinstance(default, D):
                offenders.append(f"{table.name}.{column.name}")
    assert not offenders, offenders


def test_a_band_string_still_binds_as_a_whole_number():
    """The band is stored as strings for JSON, and a price band's low is
    "477.5" - int() on that raises rather than truncating. evidenced_footprint
    holds site counts, so rounding is right and crashing is not."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1]
    app = next(c for c in (src / "api_service" / "app", src / "app")
               if (c / "domain").exists())
    promotion = (app / "domain" / "promotion.py").read_text()
    ns = {}
    exec(promotion[promotion.index("def _as_int"):
                   promotion.index("def _triangulated_index")], ns)
    assert ns["_as_int"]("341") == 341
    assert ns["_as_int"]("477.5") == 478
    assert ns["_as_int"](None) is None
    assert ns["_as_int"]("not a number") is None
