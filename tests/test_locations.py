"""Naming the sites behind a footprint count, as far as they are known.

The footprint is a count per country and site type, so "371 branches in
Germany" and a list of 371 addresses were stored identically - and the second
is far better evidence. For most outside-in cases the list will be partial: 12
known of 400. That has to be first-class rather than an edge case.
"""
import re
import types
import unicodedata
from decimal import Decimal as D

import pytest

from app.domain import locations


class _Row:
    def __init__(self, **kw):
        self.__dict__.update({"suspected_duplicate_of": None,
                              "reliability_grade": None, "city": None,
                              "name": None, "archetype": None, **kw})


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _q):
        return types.SimpleNamespace(all=lambda: self._rows)


FOOTPRINT = [{"country": "DE", "archetype": "STORE", "sites": 350},
             {"country": "DE", "archetype": "WAREHOUSE", "sites": 90},
             {"country": "US", "archetype": "DC", "sites": 2},
             {"country": "SG", "archetype": "DC", "sites": 1}]


def _named(n, country="DE", archetype="STORE"):
    return [_Row(location_id=f"{country}{archetype}{i}", country=country,
                 city=f"City{i}", name=f"Site {i}", archetype=archetype)
            for i in range(n)]


def _enum(rows, footprint=None):
    return locations.enumeration(_Session(rows), case_id="c",
                                 footprint=footprint or FOOTPRINT)


# ------------------------------------------------------- the partial case
def test_a_partial_list_is_reported_as_partial():
    """12 of 400 is the normal case, not an edge case. A list of 47 sites read
    as a footprint would be worse than having no list."""
    out = _enum(_named(40) + _named(7, archetype="WAREHOUSE"))
    assert out["enumerated"] == 47
    assert out["total"] == 443
    assert out["enumerated_share"] == "0.106"
    germany = out["by_country"]["DE"]
    assert germany["residual"] == 393
    assert germany["enumerated_mix"] == {"STORE": 40, "WAREHOUSE": 7}


def test_a_country_with_nothing_named_is_reported_as_zero():
    out = _enum(_named(40))
    assert out["by_country"]["SG"]["enumerated"] == 0
    assert out["by_country"]["SG"]["enumerated_share"] == "0.000"
    assert out["by_country"]["SG"]["residual"] == 1


def test_no_residual_rows_are_fabricated():
    """A residual is a count, not 393 anonymous locations. A reader has to be
    able to tell which sites exist as named rows and which are a tally."""
    out = _enum(_named(40))
    assert out["by_country"]["DE"]["residual"] == 310
    assert "locations" not in out, "this returns counts, never invented rows"


# --------------------------------------------- the list never raises the total
def test_more_named_than_the_total_is_a_conflict_not_a_new_total():
    """Either the locator includes sites outside the perimeter, or the filing
    is stale. Only a person can say which, and raising the total would decide
    it silently."""
    out = _enum(_named(5, country="US", archetype="DC"))
    assert out["conflicts"], "an over-enumeration must be surfaced"
    conflict = out["conflicts"][0]
    assert conflict["country"] == "US"
    assert conflict["enumerated"] == 5 and conflict["total"] == 2
    assert "does not raise the total" in conflict["note"]
    # And the share is capped rather than exceeding 1.
    assert out["by_country"]["US"]["enumerated_share"] == "1.000"


# ------------------------------------------------- the origin split, and its floor
def test_naming_sites_never_upgrades_the_unnamed_part():
    """The defect this rule exists to prevent. Taking PUBLIC_DERIVED
    unconditionally would have *upgraded* a typed footprint from
    ANALYST_ENTERED_SCOPE, so a case with no locations at all would have
    gained confidence from this feature."""
    out = _enum(_named(47))
    split = locations.origin_split(out, "DE", "ANALYST_ENTERED_SCOPE")
    assert {o for o, _ in split} == {"ANALYST_ENTERED_SCOPE"}, (
        "a typed footprint must not gain PUBLIC_DERIVED for its residual")


def test_an_evidenced_footprint_downgrades_its_unnamed_share():
    """The count is evidenced; the mix applied to the unnamed part is
    inferred, and says so."""
    out = _enum(_named(47))
    split = dict(locations.origin_split(out, "DE", "EVIDENCED_PUBLIC"))
    assert split["EVIDENCED_PUBLIC"] == D("0.107")
    assert split["PUBLIC_DERIVED"] == D("1") - D("0.107")


def test_a_country_with_nothing_named_is_priced_exactly_as_before():
    """No observed mix means nothing to infer from, so the country keeps the
    footprint's own origin and this feature changes no number."""
    out = _enum(_named(47))
    for origin in ("ANALYST_ENTERED_SCOPE", "EVIDENCED_PUBLIC"):
        assert locations.origin_split(out, "SG", origin) == [(origin, D(1))]


def test_a_fully_named_country_carries_the_footprint_origin_undiluted():
    out = _enum(_named(2, country="US", archetype="DC"),
                footprint=[{"country": "US", "archetype": "DC", "sites": 2}])
    assert locations.origin_split(out, "US", "EVIDENCED_PUBLIC") == [
        ("EVIDENCED_PUBLIC", D(1))]


def test_the_split_shares_sum_to_one():
    """The estimate apportions a component's value across the split, so a sum
    other than one silently changes the total."""
    out = _enum(_named(47))
    for origin in ("ANALYST_ENTERED_SCOPE", "EVIDENCED_PUBLIC"):
        assert sum(s for _o, s in locations.origin_split(out, "DE", origin)) == D(1)


# ---------------------------------------------- duplicates are flagged, not merged
def test_the_same_site_under_two_names_is_flagged():
    """A locator's "Niederlassung Berlin-Spandau" and an appendix's "Berlin
    Spandau" are one site. Any key that decides that will be wrong sometimes,
    so it is flagged for a person."""
    found = locations.suspected_duplicates([
        _Row(location_id="a", country="DE", city="Berlin",
             name="Niederlassung Berlin-Spandau"),
        _Row(location_id="b", country="DE", city="Berlin Spandau", name=""),
        _Row(location_id="c", country="DE", city="Hamburg",
             name="Filiale Hamburg")])
    assert len(found) == 1
    assert {found[0]["location_id"], found[0]["duplicate_of"]} == {"a", "b"}
    assert "nothing is merged automatically" in found[0]["note"]


def test_a_repeated_token_does_not_defeat_the_key():
    """"Berlin" in both the city and the name gave "berlin berlin spandau",
    which failed to match "berlin spandau" - the exact pair this is for."""
    assert locations._key(
        _Row(city="Berlin", name="Niederlassung Berlin-Spandau")) == \
        locations._key(_Row(city="Berlin Spandau", name=""))


def test_the_same_city_in_two_countries_is_not_a_duplicate():
    assert locations.suspected_duplicates([
        _Row(location_id="a", country="DE", city="Frankfurt", name="Hub"),
        _Row(location_id="b", country="US", city="Frankfurt", name="Hub")]) == []


def test_a_confirmed_duplicate_leaves_the_enumeration():
    """Marked, not deleted - and it must stop counting toward the named share
    or one site named twice reads as two."""
    rows = _named(3) + [_Row(location_id="dup", country="DE", city="City0",
                             name="Site 0", archetype="STORE",
                             suspected_duplicate_of="DESTORE0")]
    # the session filters on suspected_duplicate_of IS NULL, as the query does
    live = [r for r in rows if r.suspected_duplicate_of is None]
    assert _enum(live)["enumerated"] == 3


def test_an_empty_case_reports_nothing_to_enumerate_against():
    out = locations.enumeration(_Session([]), case_id="c", footprint=[])
    assert out["total"] == 0
    assert out["enumerated_share"] == "0"
    assert "nothing to enumerate" in out["note"]


# -------------------------------------------- the split conserves what it splits
def _apportion(total, shares):
    """The apportionment build_components uses, lifted for a direct check."""
    raw = [D(total) * s for s in shares]
    counts = [int(r) for r in raw]
    left = total - sum(counts)
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i],
                    reverse=True)[:left]:
        counts[i] += 1
    return counts


@pytest.mark.parametrize("quantity", [1, 2, 7, 47, 90, 350, 443, 2600])
def test_the_split_never_loses_a_circuit(quantity):
    """int(350 * 0.107) + int(350 * 0.893) is 349. Every split lost one, and a
    quantity of 1 vanished entirely - so the component list in the snapshot
    showed fewer circuits than the simulation produced, which is the one thing
    that list exists to make checkable."""
    shares = [D("0.107"), D("1") - D("0.107")]
    assert sum(_apportion(quantity, shares)) == quantity


def test_a_single_circuit_goes_to_the_larger_share():
    """Largest remainder, not "give it to the last part": one circuit with 90%
    named belongs to the named side."""
    assert _apportion(1, [D("0.9"), D("0.1")]) == [1, 0]
    assert _apportion(1, [D("0.1"), D("0.9")]) == [0, 1]


def test_the_value_is_scaled_by_the_share_not_the_rounded_count():
    """Rounding a value to follow a rounded quantity would move money to make a
    count tidy. The shares sum to one, so the parts sum to the whole."""
    value = D("1234567.89")
    shares = [D("0.107"), D("1") - D("0.107")]
    parts = [value * s for s in shares]
    assert sum(parts) == value
    # and still after the 2dp rounding serialisation applies
    assert sum(p.quantize(D("0.01")) for p in parts) == value


def test_every_site_driven_component_is_split():
    """L2_overlay and OPS_operations were left on one origin while the L0
    circuits driven by the same site count were split - the origin mix was
    partly enumeration-aware, which is worse than not at all because it is not
    visible in the total.

    L4_sse is driven by users, not sites, so it correctly keeps its own
    origin: the enumeration describes locations."""
    import ast
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    src = (app / "domain" / "estimate.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "build_components")
    body = ast.unparse(fn)

    unsplit = []
    for match in re.finditer(r"Component\(\s*key=(?:f)?['\"]([^'\"{]+)", body):
        key = match.group(1)
        if key.startswith("L4"):
            continue                      # users-driven, not site-driven
        context = body[max(0, match.start() - 90):match.start()]
        if not any(h in context for h in ("_site_components", "_estate_components",
                                          "_base = ")):
            unsplit.append(key)
    assert not unsplit, f"site-driven and not split: {unsplit}"


# ---------------------------------- the simulation materialises the estate
def _estate(footprint, known=None, seed=42):
    from app.domain import simulation
    arch = {"STORE": {"dual_access_probability": 0.3,
                      "primary_product": "BROADBAND_HFC",
                      "backup_product": "MOBILE_5G", "users_base": 8,
                      "bandwidth_mbps_base": 50},
            "DC": {"dual_access_probability": 1.0,
                   "primary_product": "ETHERNET", "backup_product": "ETHERNET",
                   "users_base": 5, "bandwidth_mbps_base": 10000}}
    return simulation.one_pass(seed, footprint, arch, known_locations=known)


def test_the_estate_has_exactly_as_many_sites_as_the_footprint_says():
    """The estate is what the estimate is costed from, so a count that differs
    from the footprint is a different estate priced under the same label."""
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 10},
                   {"country": "US", "archetype": "DC", "sites": 2}])
    assert out["sites"] == 12
    assert len(out["estate_full"]) == 12


def test_a_named_location_becomes_a_named_site():
    """"as much as known" means the known part is carried onto the row, not
    summarised beside it: type, address and position all reach the site the
    circuit is costed for."""
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 5}],
                  known=[{"location_id": "L1", "country": "DE",
                          "archetype": "STORE", "name": "Aldi Muenchen Ost",
                          "city": "Muenchen", "address": "Bahnhofstr 1",
                          "latitude": 48.14, "longitude": 11.58,
                          "reliability_grade": "VERY_RELIABLE"}])
    first = out["estate_full"][0]
    assert first["known"] is True
    assert first["name"] == "Aldi Muenchen Ost"
    assert first["latitude"] == 48.14
    assert first["location_id"] == "L1"
    assert out["sites_named"] == 1 and out["sites_generated"] == 4


def test_a_generated_site_carries_no_identity():
    """Structural, not a label. There is nowhere on a generated row to put a
    name, an address or a position - so nothing can drift into looking like a
    site somebody knows, which is the failure this design is most exposed to."""
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 5}],
                  known=[{"location_id": "L1", "country": "DE",
                          "archetype": "STORE", "name": "Named"}])
    generated = [r for r in out["estate_full"] if not r["known"]]
    assert len(generated) == 4
    for row in generated:
        assert row["name"] is None and row["address"] is None
        assert row["latitude"] is None and row["longitude"] is None
        assert row["location_id"] is None


def test_named_sites_come_first():
    """A reader looking at the top of the list sees what is known, rather than
    hunting for it among generated rows."""
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 6}],
                  known=[{"location_id": f"L{i}", "country": "DE",
                          "archetype": "STORE", "name": f"Site {i}"}
                         for i in range(3)])
    flags = [r["known"] for r in out["estate_full"]]
    assert flags == [True, True, True, False, False, False]


def test_every_primary_circuit_belongs_to_a_site():
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 10}])
    assert out["circuits_primary"] == out["sites"]
    assert out["circuits"] == out["circuits_primary"] + out["circuits_backup"]


def test_the_estate_is_deterministic_on_the_seed():
    """It is the basis of a published number, so the same seed and footprint
    must produce the same estate - otherwise the output hash moves between
    identical runs."""
    import json
    known = [{"location_id": "L1", "country": "DE", "archetype": "STORE",
              "name": "Named"}]
    footprint = [{"country": "DE", "archetype": "STORE", "sites": 8}]
    first = _estate(footprint, known)["estate_full"]
    second = _estate(footprint, known)["estate_full"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_a_location_for_a_kind_not_in_the_footprint_is_not_forced_in():
    """A named DC with no DC row in the footprint must not invent one: the
    footprint decides how many sites of each kind exist."""
    out = _estate([{"country": "DE", "archetype": "STORE", "sites": 3}],
                  known=[{"location_id": "L1", "country": "US",
                          "archetype": "DC", "name": "Chicago DC"}])
    assert out["sites"] == 3
    assert out["sites_named"] == 0


def test_the_stored_estate_is_bounded_and_says_what_it_dropped():
    """A JSON column is not a site register. An estate of 40,000 outlets would
    make every simulation row unreadable to protect a list nobody scrolls."""
    from app.domain import simulation
    assert simulation.MAX_ESTATE_ROWS >= 1000
