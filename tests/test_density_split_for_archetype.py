"""Giving a counted, typed footprint row the density band it arrived without.

The band is what serviceability is keyed on, so a row without one is never
tested. These assert the two halves of filling it: the split is faithful to
the governed mix and sums to the counted total, and it never substitutes a
site type to find a mix to use.
"""
import types

import pytest

from app.domain import footprint


def _mix(rows):
    """A session returning exactly these density_mix rows.

    The function filters by industry and archetype in SQL; the stub returns
    what the test declares, so each case states its own mix rather than
    depending on what the seed happens to hold.
    """
    class _Session:
        def execute(self, *_a, **_k):
            return types.SimpleNamespace(
                all=lambda: [types.SimpleNamespace(**r) for r in rows])
    return _Session()


def _row(industry, archetype, band, share):
    return {"industry": industry, "archetype": archetype,
            "density_band": band, "share": share}


# --------------------------------------------------- the split is faithful

def test_the_counted_total_is_preserved_exactly():
    """Largest remainder. The total is evidence - research counted it - so a
    split that loses or gains a site has corrupted a finding, and three
    shares over a prime total is where naive rounding does it."""
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40"),
              _row("RETAIL", "STORE", "SUBURBAN", "0.32"),
              _row("RETAIL", "STORE", "RURAL", "0.14")]),
        sites=2601, archetype="STORE", industry="RETAIL")
    assert sum(r["sites"] for r in out["rows"]) == 2601


def test_the_bands_are_renormalised_within_the_site_type():
    """density_mix is a joint distribution over (type, band) summing to one
    across the whole industry, so STORE's four rows sum to 0.96, not 1.0.
    Using the raw shares would silently lose 4% of the sites."""
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40"),
              _row("RETAIL", "STORE", "SUBURBAN", "0.32")]),
        sites=1000, archetype="STORE", industry="RETAIL")
    got = {r["density"]: r["sites"] for r in out["rows"]}
    # 0.40 and 0.32 renormalise to 5/9 and 4/9, not 0.40 and 0.32.
    assert got == {"URBAN": 556, "SUBURBAN": 444}


def test_the_row_is_split_across_bands_not_assigned_to_the_modal_one():
    """A share says a distribution. Collapsing it to the single largest band
    would put all 2,601 of Allianz's French agencies in one band and make
    serviceability all-or-nothing for them."""
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40"),
              _row("RETAIL", "STORE", "SUBURBAN", "0.32"),
              _row("RETAIL", "STORE", "RURAL", "0.14")]),
        sites=600, archetype="STORE", industry="RETAIL")
    assert len(out["rows"]) == 3


def test_the_site_type_is_carried_through_unchanged():
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40")]),
        sites=10, archetype="STORE", industry="RETAIL")
    assert {r["archetype"] for r in out["rows"]} == {"STORE"}


# ------------------------------------------- the site type is never swapped

def test_an_absent_site_type_with_no_declared_synonym_yields_nothing():
    """The reason this function exists separately from propose_split. A type
    the sector's mix does not carry, and that no entry in BAND_LAYER_SYNONYM
    names as the same layer under another name, gets no band at all rather
    than the bands of whatever else that industry happens to hold."""
    out = footprint.density_split_for_archetype(
        _mix([_row("CHEMICALS", "PLANT", "SUBURBAN", "0.768"),
              _row("CHEMICALS", "LARGE_OFFICE", "URBAN", "0.096")]),
        sites=1916, archetype="STORE", industry="CHEMICALS")
    assert out["rows"] == []
    assert out["basis"] is None
    assert "STORE" in out["note"] and "CHEMICALS" in out["note"]


def test_a_synonym_sourced_band_does_not_claim_to_be_a_direct_hit():
    """BNP's branches promote as STORE and take UNIVERSAL_BANKING's BRANCH
    bands. That is a weaker step than finding a STORE row, and the basis has
    to say so - SECTOR_LAYER_SYNONYM, not INDUSTRY_DEFAULT - or a reader
    cannot tell the two apart downstream."""
    out = footprint.density_split_for_archetype(
        _mix([_row("UNIVERSAL_BANKING", "BRANCH", "URBAN", "0.45"),
              _row("UNIVERSAL_BANKING", "LARGE_OFFICE", "URBAN", "0.02")]),
        sites=1656, archetype="STORE", industry="UNIVERSAL_BANKING")
    assert out["basis"] == "SECTOR_LAYER_SYNONYM"
    assert out["via_layer"] == "BRANCH"
    assert sum(r["sites"] for r in out["rows"]) == 1656


def test_the_generic_mix_is_used_only_for_the_same_site_type():
    """DEFAULT is a fallback across industries, never across site types."""
    out = footprint.density_split_for_archetype(
        _mix([_row("DEFAULT", "WAREHOUSE", "SUBURBAN", "0.25")]),
        sites=8, archetype="WAREHOUSE", industry="DIVERSIFIED_MINING")
    assert out["basis"] == "GENERIC_DEFAULT"
    assert out["industry"] == "DEFAULT"
    assert sum(r["sites"] for r in out["rows"]) == 8


def test_the_sector_mix_beats_the_generic_one():
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "RURAL", "0.90"),
              _row("DEFAULT", "STORE", "URBAN", "0.90")]),
        sites=100, archetype="STORE", industry="RETAIL")
    assert out["basis"] == "INDUSTRY_DEFAULT"
    assert [r["density"] for r in out["rows"]] == ["RURAL"]


# ------------------------------------------------------------- degenerate

@pytest.mark.parametrize("sites", [0, -5])
def test_nothing_is_proposed_for_a_non_positive_count(sites):
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40")]),
        sites=sites, archetype="STORE", industry="RETAIL")
    assert out["rows"] == []


def test_a_zero_weight_site_type_is_not_divided_by_zero():
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0")]),
        sites=50, archetype="STORE", industry="RETAIL")
    assert out["rows"] == []
    assert "no weight" in out["note"]


def test_the_result_says_the_band_is_a_default_and_the_count_is_not():
    """A filled band must not read as a finding: it decides which bearers are
    tested, and nobody established it for this client."""
    out = footprint.density_split_for_archetype(
        _mix([_row("RETAIL", "STORE", "URBAN", "0.40")]),
        sites=10, archetype="STORE", industry="RETAIL")
    assert "evidenced" in out["note"] and "default" in out["note"]


# ----------------------------- one layer, two names, inside one industry

def test_a_layer_recorded_under_another_name_in_the_same_sector_is_found():
    """Research types a customer-facing site as STORE; UNIVERSAL_BANKING's
    mix calls that layer BRANCH. One layer, two names, and the mismatch left
    14,746 sites unbanded and therefore never tested for serviceability.

    Four of the nine pairs were retired once their sector got a shape with a
    real STORE row; this is one of the four that remain, where BRANCH is the
    right home rather than a workaround."""
    out = footprint.density_split_for_archetype(
        _mix([_row("UNIVERSAL_BANKING", "BRANCH", "URBAN", "0.45"),
              _row("UNIVERSAL_BANKING", "BRANCH", "RURAL", "0.17")]),
        sites=5016, archetype="STORE", industry="UNIVERSAL_BANKING")
    assert sum(r["sites"] for r in out["rows"]) == 5016
    assert out["via_layer"] == "BRANCH", "the step must be visible"
    assert {r["archetype"] for r in out["rows"]} == {"STORE"}, (
        "the row keeps the type research gave it; only the bands came from "
        "the other name")


def test_the_synonym_never_crosses_an_industry():
    """The guard that keeps this from becoming the substitution the function
    exists to refuse. Shell's forecourts take INTEGRATED_OIL_GAS's own
    customer-facing bands; nothing lets them take a bank's."""
    from app.domain import bics
    for (industry, _archetype), target in bics.BAND_LAYER_SYNONYM.items():
        assert bics.band_layer_synonym(industry, "NOT_A_TYPE") is None
        assert isinstance(target, str) and target


def test_an_unmapped_pair_is_still_refused():
    """A warehouse is not a plant. Deliberately absent from the synonym
    table, so these stay unbanded and visible."""
    from app.domain import bics
    for pair in [("FOOD_MANUFACTURING", "WAREHOUSE"),
                 ("AIRLINES", "WAREHOUSE"),
                 ("HOUSEHOLD_PERSONAL_CARE", "WAREHOUSE"),
                 ("INTEGRATED_OIL_GAS", "PLANT")]:
        assert bics.band_layer_synonym(*pair) is None


def test_a_legacy_industry_code_resolves_to_the_bics_mix():
    """PARCEL_LOGISTICS is mapped to POSTAL_AND_PARCEL_NETWORK for its
    benchmark, but the mix is seeded under the BICS name - so the lookup
    missed it and a parcel network fell back to the generic many-small shape,
    which gives it a store layer and no collection points at all."""
    out = footprint.density_split_for_archetype(
        _mix([_row("POSTAL_AND_PARCEL_NETWORK", "SERVICE_POINT",
                   "URBAN", "0.29"),
              _row("POSTAL_AND_PARCEL_NETWORK", "SERVICE_POINT",
                   "RURAL", "0.07")]),
        sites=1600, archetype="SERVICE_POINT", industry="PARCEL_LOGISTICS")
    assert out["industry"] == "POSTAL_AND_PARCEL_NETWORK"
    assert sum(r["sites"] for r in out["rows"]) == 1600


def test_every_synonym_target_exists_in_that_industrys_seeded_mix():
    """The table is only useful if each target is a layer the sector's mix
    actually carries. A typo here fails silently as an unfilled band."""
    from app.domain import bics, industries
    from app import seed
    have = {(i, a) for i, a, _b, _s in seed.DENSITY_MIX}
    missing = [(i, a, t) for (i, a), t in bics.BAND_LAYER_SYNONYM.items()
               if (bics.LEGACY_TO_BICS.get(i, i), t) not in have]
    assert not missing, f"synonym targets absent from the mix: {missing}"


# ------------------------------------- the four authored sector shapes

AUTHORED = ("forecourt-network", "clinic-network", "merchant-network",
            "agency-network")


@pytest.mark.parametrize("shape", AUTHORED)
def test_an_authored_shape_sums_to_exactly_one(shape):
    """Not approximately. propose_split multiplies a registered total by each
    share and corrects by largest remainder, so a mix summing to 2.0 makes
    `total - sum(counts)` negative and the correction inflates instead of
    trimming."""
    from decimal import Decimal
    from app.domain import industries
    total = sum(Decimal(s) for _a, _b, s in industries.SHAPES[shape])
    assert total == Decimal("1.0000"), f"{shape} sums to {total}"


@pytest.mark.parametrize("shape", AUTHORED)
def test_an_authored_shape_has_no_duplicate_type_and_band(shape):
    from app.domain import industries
    pairs = [(a, b) for a, b, _s in industries.SHAPES[shape]]
    assert len(pairs) == len(set(pairs)), f"{shape} repeats a (type, band)"


@pytest.mark.parametrize("shape,layer", [
    ("forecourt-network", "STORE"), ("clinic-network", "STORE"),
    ("merchant-network", "STORE"), ("agency-network", "STORE")])
def test_the_layer_the_shape_exists_for_is_the_largest_in_it(shape, layer):
    """Each of these replaced a generic shape that had no row for this layer
    at all, which is what left 13,038 sites unbanded. If it is not the
    dominant layer the shape has not done its job."""
    from decimal import Decimal
    from app.domain import industries
    totals = {}
    for archetype, _band, share in industries.SHAPES[shape]:
        totals[archetype] = totals.get(archetype, Decimal("0")) + Decimal(share)
    assert max(totals, key=lambda a: totals[a]) == layer


@pytest.mark.parametrize("shape,representative", [
    # bics.density_mix_rows substitutes the benchmark's representative site
    # into the shape's dominant slot, but only when the shape does not
    # already contain it. Each of these does, so the authored distribution
    # survives - without this the forecourt layer would be overwritten by
    # the refinery the benchmark names.
    ("forecourt-network", "PLANT"), ("clinic-network", "TERMINAL"),
    ("merchant-network", "PLANT"), ("agency-network", "LARGE_OFFICE")])
def test_the_representative_site_is_already_in_the_shape(shape, representative):
    from app.domain import industries
    assert representative in {a for a, _b, _s in industries.SHAPES[shape]}


def test_the_four_sectors_now_hit_their_own_store_row_directly():
    """The point of the exercise: these stop being synonym lookups and
    report INDUSTRY_DEFAULT, because the band now comes from a profile
    authored for this site type rather than borrowed from a branch."""
    from app.domain import bics
    for industry in ("INSURANCE", "BUILDING_MATERIALS", "HOSPITAL",
                     "INTEGRATED_OIL_GAS"):
        assert bics.band_layer_synonym(industry, "STORE") is None
