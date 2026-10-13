"""Choosing between several candidates that describe the same estate layer.

evidenced_footprint holds one row per (country, archetype) - promote deletes
and reinserts - so when several candidates shared a pair, write order
decided which survived.

Simmons Bank's locations domain returned a 222-branch national total AND a
six-state breakdown of the same network, every row typed STORE. The estate
kept Kansas's 4.
"""
import pytest

from app.domain import promotion


def _entry(cid, country, archetype, sites):
    return {"candidate_id": cid,
            "quantity": {"label": f"{archetype} - a layer", "country": country,
                         "unit": "sites", "value": str(sites)}}


def _sites(entries):
    return sorted(promotion._sites_from(e["quantity"]) for e in entries)


# ------------------------------------------------------- the choice made

def test_the_largest_row_wins_not_the_last_written():
    """Write order is not evidence. Kansas's 4 beat a 222 national total
    only because it happened to be promoted last."""
    kept, _ = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 222), _entry("b", "US", "STORE", 65),
        _entry("c", "US", "STORE", 4)])
    assert _sites(kept) == [222]


def test_the_rows_are_not_summed():
    """Summing double-counts: research returns a total alongside subsets of
    it, so 222 branches plus a six-state breakdown of the same branches is
    459 for a bank that has 230."""
    kept, _ = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 222), _entry("b", "US", "STORE", 65),
        _entry("c", "US", "STORE", 57), _entry("d", "US", "STORE", 47)])
    assert _sites(kept) == [222]


def test_different_pairs_are_untouched():
    kept, sup = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 10), _entry("b", "DE", "STORE", 20),
        _entry("c", "US", "WAREHOUSE", 5)])
    assert _sites(kept) == [5, 10, 20]
    assert sup == []


def test_a_single_row_reports_nothing():
    kept, sup = promotion._one_row_per_pair([_entry("a", "GB", "STORE", 50)])
    assert _sites(kept) == [50] and sup == []


def test_a_non_footprint_candidate_passes_through():
    """Prices and anchors are keyed differently and must not be collapsed."""
    price = {"candidate_id": "p",
             "quantity": {"label": "DIA 100 Mbps MRC", "country": "US",
                          "unit": "USD/month", "value": "500",
                          "bandwidth_mbps": 100}}
    kept, sup = promotion._one_row_per_pair(
        [price, _entry("a", "US", "STORE", 10)])
    assert len(kept) == 2 and sup == []


# ----------------------------------------------------- what it reports

def test_the_displaced_rows_are_reported():
    """The alternatives research found are part of what it found."""
    _kept, sup = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 222), _entry("b", "US", "STORE", 65),
        _entry("c", "US", "STORE", 4)])
    assert len(sup) == 1
    assert sup[0]["kept"] == 222
    assert sup[0]["also_found"] == [4, 65]
    assert sup[0]["country"] == "US" and sup[0]["archetype"] == "STORE"


def test_a_likely_partition_is_flagged():
    """The one shape where the largest undercounts: several regions and no
    total. Nothing in the sample looks like this - the closest is 1.07x -
    so it is reported rather than handled, because a rule invented for a
    case that has not happened would be guessing twice."""
    _kept, sup = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 100), _entry("b", "US", "STORE", 100),
        _entry("c", "US", "STORE", 100), _entry("d", "US", "STORE", 100)])
    assert sup[0]["parts_exceed_kept"] is True


def test_a_total_with_its_parts_is_not_flagged_as_a_partition():
    """Simmons: parts sum to 237 against a 222 total, which is 1.07x and
    exactly what a near-complete breakdown looks like."""
    _kept, sup = promotion._one_row_per_pair([
        _entry("a", "US", "STORE", 222), _entry("b", "US", "STORE", 65),
        _entry("c", "US", "STORE", 57), _entry("d", "US", "STORE", 47),
        _entry("e", "US", "STORE", 45), _entry("f", "US", "STORE", 19),
        _entry("g", "US", "STORE", 4)])
    assert sup[0]["parts_exceed_kept"] is False


# ------------------------------------------- the real pairs it was built on

@pytest.mark.parametrize("name,values,expected", [
    ("simmons-bank", [4, 19, 45, 47, 57, 65, 222], 222),
    ("deutsche-post-dhl", [38, 46, 81], 81),
    ("lufthansa", [3, 6, 10], 10),
    ("tesco", [45, 806, 3829], 3829),
    ("basf", [1, 54], 54),
])
def test_the_sample_sets_multi_row_pairs(name, values, expected):
    """Every multi-row pair across the 26 companies, and in each the largest
    is the right answer and the sum is not."""
    kept, _ = promotion._one_row_per_pair(
        [_entry(str(i), "XX", "STORE", v) for i, v in enumerate(values)])
    assert _sites(kept) == [expected]
    assert sum(values) != expected or len(values) == 1
