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
    """Shell's forecourts promote as STORE and take INTEGRATED_OIL_GAS's
    BRANCH bands. That is a weaker step than finding a STORE row, and the
    basis has to say so - SECTOR_LAYER_SYNONYM, not INDUSTRY_DEFAULT - or a
    reader cannot tell the two apart downstream."""
    out = footprint.density_split_for_archetype(
        _mix([_row("INTEGRATED_OIL_GAS", "BRANCH", "URBAN", "0.466"),
              _row("INTEGRATED_OIL_GAS", "LARGE_OFFICE", "URBAN", "0.352")]),
        sites=1916, archetype="STORE", industry="INTEGRATED_OIL_GAS")
    assert out["basis"] == "SECTOR_LAYER_SYNONYM"
    assert out["via_layer"] == "BRANCH"
    assert sum(r["sites"] for r in out["rows"]) == 1916


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
    """Research types a customer-facing site as STORE; INSURANCE's mix calls
    that layer BRANCH. One layer, two names, and the mismatch left 14,746
    sites unbanded and therefore never tested for serviceability."""
    out = footprint.density_split_for_archetype(
        _mix([_row("INSURANCE", "BRANCH", "URBAN", "0.45"),
              _row("INSURANCE", "BRANCH", "RURAL", "0.17")]),
        sites=5016, archetype="STORE", industry="INSURANCE")
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
