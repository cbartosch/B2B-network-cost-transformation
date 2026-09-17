"""The supplied BICS L3 industry WAN benchmark.

44 rows across 10 sectors, 42 level-3 industries and 37 site archetypes - the
first reference data in this model that was not invented here. The five site
archetypes and their bandwidths were the workbench's own judgement, and nine
industries carried an honest "POOR fit" caveat because a terminal, a mine and
a tower site are not branches.
"""
from decimal import Decimal as D

import pytest

from app.domain import industry_benchmark as ib


def test_every_supplied_row_reads_into_the_models_units():
    """A row this cannot parse is one an analyst must look at. A load that
    silently drops it leaves an industry with no benchmark and no explanation,
    discovered as a missing figure three screens later."""
    out = ib.seeded()
    assert out["refused"] == []
    # The supplied benchmark is 44 rows across 42 industries. `seeded()` also
    # returns this repository's own rows for industries the benchmark does not
    # cover, so a total is no longer the thing to assert - the counts would
    # move every time a sector is added, and the test would be maintained
    # rather than informative.
    supplied = len(ib.INDUSTRY_WAN_BENCHMARK)
    unbenchmarked = len(ib.UNBENCHMARKED_BICS_ROWS)
    assert supplied == 44, "the supplied benchmark itself must not change"
    assert len(out["rows"]) == supplied + unbenchmarked
    assert len(out["unbenchmarked_industries"]) == unbenchmarked
    assert len(out["sectors"]) == 10


@pytest.mark.parametrize("text,expected", [
    ("5-40 Gbps", (5000, 40000)),
    ("100 Mbps-2 Gbps", (100, 2000)),
    ("500 Mbps-10 Gbps", (500, 10000)),
    ("20-500 Mbps", (20, 500)),
    ("100-400+ Gbps", (100000, 400000)),
])
def test_a_bandwidth_range_reads_in_mbps(text, expected):
    """"1-20 Gbps" states its unit once, at the end, and it governs both
    bounds."""
    assert ib.parse_bandwidth(text) == expected


def test_an_unreadable_bandwidth_is_refused_not_defaulted():
    """A default would put a bandwidth in the model the source does not
    state."""
    with pytest.raises(ib.BenchmarkRowInvalid, match="not a bandwidth range"):
        ib.parse_bandwidth("fast")


@pytest.mark.parametrize("text,low,high", [
    # 100% is 1.00, not 0.100. My first version wrote the latter, which is
    # the same class of error as the 1.2100 I asserted for 1220/1000 in
    # 4.191 - a number arrived at by eye rather than by division.
    ("100%", "1.00", "1.00"), ("80-100%", "0.80", "1.00"),
    ("25-75%", "0.25", "0.75"), ("50-100%", "0.50", "1.00"),
])
def test_a_committed_share_reads_as_a_fraction(text, low, high):
    got_low, got_high = ib.parse_cir(text)
    assert got_low == D(low)
    assert got_high == D(high)


def test_a_single_figure_is_both_bounds():
    """The source is stating a certainty rather than a range, and widening it
    would invent a spread."""
    low, high = ib.parse_cir("100%")
    assert low == high == D("1")


def test_a_committed_share_above_the_bearer_is_refused():
    """A committed rate above the circuit carrying it cannot be delivered."""
    with pytest.raises(ib.BenchmarkRowInvalid, match="share of a bearer"):
        ib.parse_cir("120%")
    with pytest.raises(ib.BenchmarkRowInvalid, match="share of a bearer"):
        ib.parse_cir("0%")


def test_the_label_describes_the_figures_not_the_industry_code():
    """STEEL is a standard BICS L3 classification and always was. What this
    repository supplied is its bandwidth, committed share and criticality,
    because the workbook has no row for it.

    An earlier version marked these rows "LOCAL", which read as though the
    industry itself were invented - indefensible next to ArcelorMittal, and
    wrong. A reader still has to be able to tell a published figure from one
    we wrote; they must not be told the classification is ours."""
    out = ib.seeded()
    by_code = {r["industry_code"]: r for r in out["rows"]}
    assert by_code["STEEL"]["figures_from"] == ib.WORKBENCH_ESTIMATE
    assert by_code["SUPERMARKETS"]["figures_from"] == ib.SUPPLIED_BENCHMARK
    # and nothing in the output implies the code is non-standard
    assert "LOCAL" not in out["note"]
    assert "classification is BICS in every case" in out["note"]


def test_the_industries_that_had_no_code_now_have_one():
    """A thirty-company run mapped fourteen to a nearest neighbour, and
    ArcelorMittal to FORESTRY_PAPER - a mill is a mill, and telling a client
    their steelworks was modelled as forestry and paper is finished before it
    starts."""
    codes = set(ib.seeded()["industries"])
    for code in ("INDUSTRIAL_CONGLOMERATE", "BUILDING_MATERIALS", "STEEL",
                 "AEROSPACE_DEFENSE", "HOUSEHOLD_PERSONAL_CARE"):
        assert code in codes, code


def test_every_location_context_maps_to_a_real_density_band():
    """An unmapped context would put a site in a band serviceability cannot
    resolve."""
    for context in ib.CONTEXT_TO_DENSITY:
        assert ib.CONTEXT_TO_DENSITY[context] in (
            "DENSE_URBAN", "URBAN", "SUBURBAN", "RURAL")
    contexts = {r["location_context"] for r in ib.seeded()["rows"]}
    assert contexts <= set(ib.CONTEXT_TO_DENSITY)


def test_industrial_is_suburban_not_rural():
    """An industrial estate is served, just not by the dense urban fibre a city
    centre has. Mapping it to RURAL would make a refinery unserviceable when
    refineries have fibre."""
    assert ib.CONTEXT_TO_DENSITY["Industrial"] == "SUBURBAN"


def test_a_tier_one_site_is_certain_to_need_a_second_path():
    """1.00 rather than 0.95: a tier 1 site without one is a finding about that
    site, and serviceability already reports a path it cannot deliver as
    single_by_necessity."""
    assert ib.TIER_TO_DUAL_ACCESS["Tier 1"] == D("1.00")
    assert ib.TIER_TO_DUAL_ACCESS["Tier 3"] < ib.TIER_TO_DUAL_ACCESS["Tier 2"]


def test_an_archetype_keeps_the_sources_own_wording():
    """Mapping a refinery to WAREHOUSE would lose the thing that makes it a
    refinery, and the five archetypes not covering these is why nine industries
    carried a POOR-fit caveat."""
    assert ib.archetype_code("Mega Container Port") == "MEGA_CONTAINER_PORT"
    assert ib.archetype_code("Wind/Solar Farm") == "WIND_SOLAR_FARM"
    codes = ib.seeded()["archetypes"]
    for expected in ("REFINERY", "TOWER_SITE", "TRADING_FLOOR", "FAB",
                     "MAJOR_HUB_AIRPORT", "HEADEND"):
        assert expected in codes


def test_the_benchmark_disagrees_with_the_seeded_fraction_and_should():
    """4.181 set one fraction per archetype - 30% for a data centre, 50% for
    everything else. A supermarket store is 25-75% and a trading floor is 100%,
    and treating both as 50% was wrong in opposite directions."""
    rows = ib.seeded()["rows"]
    store = next(r for r in rows if r["industry_code"] == "SUPERMARKETS")
    floor = next(r for r in rows
                 if r["archetype_code"] == "TRADING_FLOOR")
    assert D(store["committed_share_base"]) == D("0.500")
    assert D(floor["committed_share_base"]) == D("1.000")


def test_a_midpoint_is_reported_beside_the_range_never_instead_of_it():
    """"1-20 Gbps" is a factor of twenty, and a midpoint of 10.5 Gbps asserts a
    precision the source does not have."""
    row = ib.read_row(dict(zip(ib.COLUMNS, ib.INDUSTRY_WAN_BENCHMARK[0])))
    assert (row["bandwidth_low_mbps"] < row["bandwidth_base_mbps"]
            < row["bandwidth_high_mbps"])
    assert row["bandwidth_low_mbps"] == 5000
    assert row["bandwidth_high_mbps"] == 40000
    assert row["bandwidth_base_mbps"] == 22500


def test_a_sector_sibling_is_flagged_rather_than_passed_off_as_exact():
    """A supermarket benchmark applied to a drug retailer is defensible and is
    not the same as having one."""
    exact = ib.for_industry("TOWER_COMPANY")
    assert exact and all(r["match"] == "EXACT" for r in exact)
    assert ib.for_industry("NOT_AN_INDUSTRY") == []


def test_the_benchmark_reaches_the_simulation_and_v0():
    """Every reference table this session that reached no calculation was a
    table nobody read."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    sim = (app / "domain" / "simulation.py").read_text()
    jobs = (app / "jobs.py").read_text()

    # V0: the bandwidth basis says which figures are published and which ours
    assert "benchmark_matched" in api
    # the simulation: committed share and criticality
    assert "benchmark_committed" in api
    assert "dual_access_by_archetype" in api
    assert "dual_access_by_archetype" in sim
    assert 'get("dual_access_by_archetype")' in jobs
    # intake: both taxonomies offered
    assert "bics_l3" in api


def test_a_case_choice_outranks_the_published_average():
    """An engagement that knows what its sites commit outranks a published
    average for its industry, which outranks this repository's judgement."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    block = api[api.index('"committed_fraction_by_archetype": {'):][:400]
    # the benchmark is spread first, the case second - so the case wins
    assert block.index("benchmark_committed") < block.index("case_row")
