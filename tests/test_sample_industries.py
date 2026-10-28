"""Every industry the sample spec researches under is one the seed can price.

An unknown code does not fail: it silently sizes and prices the estate on the
DEFAULT shape with no benchmark behind it. Maersk (SHIPPING_LOGISTICS) and
Michelin (AUTOMOTIVE_PARTS) ran that way, unreported, until these tests.
"""
import json
import pathlib

from app.domain import bics
from app.seed import ARCHETYPE_BANDWIDTH, DENSITY_MIX

SPEC = pathlib.Path(__file__).resolve().parents[1] / "samples" / "companies.json"
INDUSTRIES = {c["slug"]: c["industry"]
              for c in json.loads(SPEC.read_text("utf-8"))["companies"]}


def test_every_sample_industry_has_bandwidth_rows():
    priced = {i for i, _a, _m in ARCHETYPE_BANDWIDTH}
    unknown = {s: i for s, i in INDUSTRIES.items() if i not in priced}
    assert not unknown, f"no seeded bandwidth for these industries: {unknown}"


def test_every_sample_industry_has_an_estate_mix():
    mixed = {i for i, _a, _b, _s in DENSITY_MIX}
    unknown = {s: i for s, i in INDUSTRIES.items() if i not in mixed}
    assert not unknown, f"no estate mix for these industries: {unknown}"


def test_every_sample_industry_reaches_a_published_benchmark():
    """A BICS code, or a code mapped to one - not a grade E seeded default."""
    unmapped = {s: i for s, i in INDUSTRIES.items()
                if bics.benchmark_code(i) is None}
    assert not unmapped, f"no benchmark behind these industries: {unmapped}"
