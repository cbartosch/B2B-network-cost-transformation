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

def test_an_absent_site_type_yields_nothing_rather_than_another_type_s_bands():
    """The defect this guards is the reason the function exists separately
    from propose_split. Shell's 1,916 German service stations promote as
    STORE; the INTEGRATED_OIL_GAS mix carries BRANCH, LARGE_OFFICE and DC and
    no STORE at all. Falling back to the industry's other rows would price
    forecourts as bank branches."""
    out = footprint.density_split_for_archetype(
        _mix([_row("INTEGRATED_OIL_GAS", "BRANCH", "URBAN", "0.466"),
              _row("INTEGRATED_OIL_GAS", "LARGE_OFFICE", "URBAN", "0.352")]),
        sites=1916, archetype="STORE", industry="INTEGRATED_OIL_GAS")
    assert out["rows"] == []
    assert out["basis"] is None
    assert "STORE" in out["note"] and "INTEGRATED_OIL_GAS" in out["note"]


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
