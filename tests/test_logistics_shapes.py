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
    # The retail layer is now split between staffed counters and unmanned
    # lockers, because they are not the same circuit: a parcel shop is a
    # counter inside a newsagent, usually carried by the host's line, and a
    # packstation is one unmanned device on cellular in a car park. Both were
    # STORE, which priced them as staffed outlets with a LAN and a till.
    collection = mix["SERVICE_POINT"] + mix["SELF_SERVICE_TERMINAL"]
    assert collection > Decimal("0.85"), dict(mix)
    assert mix["SERVICE_POINT"] > 0 and mix["SELF_SERVICE_TERMINAL"] > 0, (
        "the two must be modelled separately, not collapsed")
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


# ------------------------- unmanned single-device sites
def test_the_unmanned_site_types_exist_and_differ_from_a_store():
    """A STORE is a staffed outlet with a till, a LAN and twelve people. A
    packstation, a vending machine and a cash machine are none of those: one
    device, nobody there, and usually no fixed line.

    Pricing 30,000 packstations as cable-connected shops overstates them
    several times over, and it is the largest row in a postal estate."""
    from app.seed import ARCHETYPES

    priors = {row[0]: row for row in ARCHETYPES}
    for name in ("SERVICE_POINT", "SELF_SERVICE_TERMINAL", "ATM"):
        assert name in priors, name

    store = priors["STORE"]
    for name in ("SELF_SERVICE_TERMINAL", "ATM"):
        assert priors[name][1] == 0, f"{name} has nobody there"
        assert priors[name][4] == "MOBILE_5G", (
            f"{name} is cellular first - there is rarely a fixed line where "
            f"these are sited")
    assert priors["SERVICE_POINT"][1] < store[1], (
        "a hosted counter is smaller than a staffed outlet")


def test_a_cash_machine_carries_a_higher_posture_than_a_kiosk():
    """Physically the same and a different claim. Cash is at stake and card
    data is in PCI scope, so availability and path diversity matter far more
    than capacity."""
    from app.seed import ARCHETYPES

    priors = {row[0]: row for row in ARCHETYPES}
    atm, kiosk = priors["ATM"], priors["SELF_SERVICE_TERMINAL"]
    assert float(atm[3]) > float(kiosk[3]), "an ATM is likelier to be dual-fed"
    assert float(atm[6]) > float(kiosk[6]), (
        "and its session must not degrade mid-transaction")


def test_every_new_type_has_a_fallback_bandwidth_in_every_shape():
    """An archetype with no figure is unpriceable scope, which is what four
    guards reported the last time the vocabulary grew."""
    from app.domain import industries

    for shape, table in industries.SHAPE_BANDWIDTH.items():
        for name in ("SERVICE_POINT", "SELF_SERVICE_TERMINAL", "ATM"):
            assert name in table, (shape, name)
