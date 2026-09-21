"""Resilience reaching the estate it is supposed to describe.

The industry benchmark's criticality tier, committed share and dual-access
probability applied only where its representative archetype appeared in the
industry's estate mix, and it does not for 43 of 47 industries. Chemicals,
household products and semiconductors returned byte-identical baselines
despite benchmark rows differing by nearly 10x in bandwidth.

Bandwidth never had this problem, because archetype_bandwidth is keyed
(industry, archetype) - the key the estate mix uses. Resilience is now keyed
the same way.
"""
from decimal import Decimal as D

from app.domain import resilience


def test_a_data_centre_stays_diverse_in_every_industry():
    """A pure industry multiplier would give a Tier 3 industry's data centre
    half the diversity of a Tier 1 one, which is wrong: a data centre is a
    data centre. The composition closes a gap rather than scaling a level."""
    for tier in ("Tier 1", "Tier 2", "Tier 3", None):
        out = resilience.derive(archetype_dual="1.00",
                                archetype_committed="0.30",
                                industry_tier=tier)
        assert out["dual_access_probability"] == D("1")


def test_a_store_moves_with_the_industry():
    """And is monotone in criticality: a store in a regulated industry has a
    second path more often than a store in a discretionary one."""
    got = [resilience.derive(archetype_dual="0.35", archetype_committed="0.50",
                             industry_tier=t)["dual_access_probability"]
           for t in ("Tier 3", "Tier 2", "Tier 1")]
    assert got == sorted(got), got
    assert got[0] == D("0.35"), "Tier 3 leaves the site type's own need alone"
    assert got[-1] > D("0.7"), "Tier 1 closes most of the gap"


def test_no_industry_leaves_the_baseline_untouched():
    """The correct answer for an industry the benchmark does not cover, and
    what keeps this callable for an estate with no industry at all."""
    out = resilience.derive(archetype_dual="0.55", archetype_committed="0.50")
    assert out["dual_access_probability"] == D("0.55")
    assert out["committed_fraction"] == D("0.50")
    assert out["industry_tier"] is None


def test_a_retuned_threshold_cannot_exceed_certainty():
    """Both constants are governed, so a steward can set them wrong. A
    probability above 1 would propagate into a circuit count."""
    out = resilience.derive(archetype_dual="0.55", archetype_committed="0.50",
                            industry_tier="Tier 1", closure="9")
    assert out["dual_access_probability"] == D("1")


def test_the_derivation_reports_its_own_arithmetic():
    """A figure modulated by an industry must not be indistinguishable from
    one that was not - the same rule currency.convert follows."""
    out = resilience.derive(archetype_dual="0.35", archetype_committed="0.50",
                            industry_tier="Tier 1", industry_committed="1.00")
    assert out["closure"] == D("0.65")
    assert out["blend"] == D("0.5")
    assert "modulated by industry Tier 1" in out["basis"]


# --------------------------------------------- the generated table
def test_every_estate_pair_gets_a_row():
    """Keyed on the pairs the estate mix produces, so every row is reachable
    by construction. Generating for the benchmark's archetypes instead is the
    defect this replaces."""
    from app.seed import DENSITY_MIX, _archetype_resilience

    pairs = {(i, a) for i, a, _b, _s in DENSITY_MIX}
    rows = {(i, a) for i, a, _d, _c, _t in _archetype_resilience()}
    from app.seed import ARCHETYPES
    known = {a for a, *_rest in ARCHETYPES}
    missing = {(i, a) for i, a in pairs if a in known} - rows
    assert not missing, sorted(missing)[:8]


def test_two_industries_with_different_postures_now_differ():
    """Chemicals is Tier 1 with 0.900 committed; household care is Tier 2 with
    0.650. They shared a shape and produced identical estates."""
    from app.seed import _archetype_resilience

    rows = {(i, a): (d, c) for i, a, d, c, _t in _archetype_resilience()}
    assert rows[("CHEMICALS", "WAREHOUSE")] != \
        rows[("HOUSEHOLD_PERSONAL_CARE", "WAREHOUSE")]


def test_the_most_critical_row_sets_an_industrys_posture():
    """An integrated oil company has both an HQ and a refinery. An estate's
    resilience is set by what it cannot afford to lose, not by its average."""
    from app.domain import industry_benchmark
    from app.seed import ARCHETYPES, DENSITY_MIX

    rows = resilience.rows_for(
        [(a, d, cf) for a, _u, _bw, d, _pp, _bp, cf in ARCHETYPES],
        industry_benchmark.seeded()["rows"],
        {(i, a) for i, a, _b, _s in DENSITY_MIX})
    tiers = {i: t for i, _a, _d, _c, t in rows if i == "INTEGRATED_OIL_GAS"}
    assert tiers.get("INTEGRATED_OIL_GAS") == "Tier 1"


def test_the_route_reads_the_reachable_table():
    """The two dicts the simulation reads were built from the benchmark's own
    rows, keyed on an archetype the estate usually does not contain."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "select(db.archetype_resilience)" in api
    assert '_row["archetype_code"]: _row["committed_share_base"]' not in api
    assert "resilience_basis" in api, (
        "the two axes must be named separately in the pin")
