"""Postal and logistics estates are shaped unlike anything else.

LOGISTICS sat on `few-large`, which is 65% LARGE_OFFICE - so a logistics
company came out two-thirds offices with distribution centres at a quarter,
inverting what its own benchmark says the industry is built around.

A swap was tried first, promoting the benchmark's representative archetype to
the dominant slot. It made the postal estate 91% sortation hubs. The benchmark
names the site an industry is BUILT AROUND, not the site there are most of -
for a chemicals company those coincide, for a postal network or a tower company
they are opposite, and a rule assuming they coincide is wrong exactly where the
operationally important site is rare.

So: shapes, not reordering.
"""
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


def test_a_parcel_network_is_mostly_retail_collection_points():
    """91% retail, a thin depot layer, a few dozen hubs. Modelled as
    few-large it had no retail layer at all."""
    from app.seed import DENSITY_MIX

    mix = defaultdict(Decimal)
    for industry, archetype, _band, share in DENSITY_MIX:
        if industry == "POSTAL_AND_PARCEL_NETWORK":
            mix[archetype] += Decimal(share)
    assert mix["STORE"] > Decimal("0.85"), dict(mix)
    assert mix["TERMINAL"] > 0, "a parcel network has sortation hubs"
    assert mix["TERMINAL"] < Decimal("0.05"), "and very few of them"


def test_a_distribution_estate_is_warehouses_first():
    from app.seed import DENSITY_MIX

    for industry in ("LOGISTICS", "WAREHOUSING"):
        mix = defaultdict(Decimal)
        for code, archetype, _band, share in DENSITY_MIX:
            if code == industry:
                mix[archetype] += Decimal(share)
        lead = max(mix, key=lambda a: mix[a])
        assert lead == "WAREHOUSE", (industry, lead, dict(mix))


def test_the_representative_archetype_never_reorders_a_shape():
    """The swap inverted the postal estate. A shape that already contains the
    representative archetype was authored deliberately."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "bics.py").read_text()
    assert "lead != incumbent and lead not in totals" in source, (
        "substitution must fill an absence, never reorder")
    assert "else incumbent if archetype == lead" not in source


def test_shape_of_bics_has_no_duplicate_keys():
    """A duplicate key is silent: the later entry wins and the earlier one
    looks applied. Changing LOGISTICS by prepending an entry did nothing for
    exactly that reason, and the audit found the same shape in the benchmark
    table."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "bics.py").read_text()
    start = source.index("SHAPE_OF_BICS = {")
    end = source.index("\n}", start)
    keys = re.findall(r'"([A-Z_]+)": "[a-z-]+"', source[start:end])
    duplicated = [k for k, n in Counter(keys).items() if n > 1]
    assert not duplicated, duplicated


def test_every_shape_sums_to_one():
    from app.domain import industries

    for name, rows in industries.SHAPES.items():
        total = sum(Decimal(share) for _a, _b, share in rows)
        assert total == Decimal("1.0000"), (name, str(total))


def test_a_refused_benchmark_row_is_reported_not_dropped():
    """The postal row was refused for naming an unknown location context, and
    the loader said which six it knows. A silent drop would have left the
    industry missing and the analyst finding out three screens later."""
    from app.domain import industry_benchmark

    assert industry_benchmark.seeded()["refused"] == []


def test_the_postal_figures_are_marked_as_ours():
    """The supplied benchmark has no postal row. The code is standard BICS;
    the figures are this repository's."""
    from app.domain import industry_benchmark

    rows = {r["industry_code"]: r for r in industry_benchmark.seeded()["rows"]}
    assert rows["POSTAL_AND_PARCEL_NETWORK"]["figures_from"] == \
        industry_benchmark.WORKBENCH_ESTIMATE
