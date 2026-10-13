"""Site types a company's scope rules out.

A declared footprint says what is IN. It had no way to say what is OUT, and
the merge cannot tell "the disclosure does not list this" from "the
disclosure excludes this" - it adds any researched pair the disclosure
lacks, which is right for a layer nobody published and wrong for one
somebody ruled out.

UPS found it. Its spec excluded the franchised UPS Store network in a
comment, research promoted 5,603 of them, and the estate went from 1,038
sites to 6,692 - pricing retail circuits UPS does not buy. The exclusion was
prose in a JSON file and nothing read it.
"""
import importlib.util
import pathlib

import pytest


def _driver():
    for root in (pathlib.Path("/app"),
                 pathlib.Path(__file__).resolve().parents[1]):
        f = root / "tools" / "run_samples.py"
        if f.exists():
            spec = importlib.util.spec_from_file_location("_rs_excl", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("tools/run_samples.py not present")


@pytest.fixture()
def driver():
    return _driver()


def _spec(excluded=None, declared=None):
    return {"slug": "t", "declared_footprint": declared or [],
            "excluded": excluded or []}


# --------------------------------------------------------- what it matches

def test_an_excluded_pair_is_recognised(driver):
    rules = driver._scope_exclusions(
        _spec([{"country": "US", "archetype": "STORE", "reason": "franchised"}]))
    assert driver._excluded_by(rules, "US", "STORE") == "franchised"


def test_an_exclusion_without_a_country_covers_every_country(driver):
    """A franchise or dealer network is rarely out of scope in one market and
    in scope in the next."""
    rules = driver._scope_exclusions(
        _spec([{"archetype": "STORE", "reason": "franchised"}]))
    for country in ("US", "DE", "GB"):
        assert driver._excluded_by(rules, country, "STORE") == "franchised"


def test_a_country_scoped_exclusion_does_not_leak(driver):
    rules = driver._scope_exclusions(
        _spec([{"country": "US", "archetype": "STORE", "reason": "franchised"}]))
    assert driver._excluded_by(rules, "DE", "STORE") is None


def test_another_site_type_is_untouched(driver):
    rules = driver._scope_exclusions(
        _spec([{"archetype": "STORE", "reason": "franchised"}]))
    assert driver._excluded_by(rules, "US", "WAREHOUSE") is None


def test_matching_is_case_insensitive(driver):
    rules = driver._scope_exclusions(
        _spec([{"country": "us", "archetype": "store", "reason": "franchised"}]))
    assert driver._excluded_by(rules, "US", "STORE") == "franchised"


def test_no_exclusions_matches_nothing(driver):
    assert driver._scope_exclusions(_spec()) == []
    assert driver._excluded_by([], "US", "STORE") is None


# ------------------------------------------------------------ what it refuses

def test_an_exclusion_must_give_a_reason(driver):
    """It drops researched evidence. Without a reason it is
    indistinguishable from a typo six months later."""
    with pytest.raises(SystemExit) as e:
        driver._scope_exclusions(_spec([{"archetype": "STORE"}]))
    assert "reason" in str(e.value)


def test_an_exclusion_must_name_a_site_type(driver):
    with pytest.raises(SystemExit):
        driver._scope_exclusions(_spec([{"reason": "franchised"}]))


def test_a_pair_may_be_both_declared_and_excluded(driver):
    """An exclusion bars RESEARCH from a site type; it does not touch the
    declared footprint, so the two are not in conflict.

    Refused at first, on the reasoning that one of them had to be a mistake.
    UNFI showed otherwise: it operates about 75 Cub Foods and Shoppers
    stores, and its 10-K also states the ~60,000 customer locations it
    SUPPLIES. Both are true, both are STORE, and only one is UNFI's estate.
    Research promoted the 60,000, superseding the declared 75 by 800x, and
    the simulation refused the row at its 50,000 cap.
    """
    rules = driver._scope_exclusions(_spec(
        excluded=[{"archetype": "STORE", "reason": "customers, not sites"}],
        declared=[{"country": "US", "archetype": "STORE", "sites": 75,
                   "density": "SUBURBAN"}]))
    assert driver._excluded_by(rules, "US", "STORE") == "customers, not sites"


# ------------------------------------------------------- the committed spec

def test_ups_excludes_its_franchised_store_network():
    """The case this exists for. Without it UPS prices 5,603 retail circuits
    it does not buy."""
    import json
    for root in (pathlib.Path("/app"),
                 pathlib.Path(__file__).resolve().parents[1]):
        f = root / "samples" / "companies.json"
        if f.exists():
            break
    else:
        pytest.skip("spec not present")
    ups = next(c for c in json.loads(f.read_text("utf-8"))["companies"]
               if c["slug"] == "ups")
    rules = ups.get("excluded") or []
    assert any(r["archetype"] == "STORE" for r in rules)
    assert all(r.get("reason") for r in rules)


def test_unfi_bars_researched_stores_while_keeping_its_own():
    """The case that relaxed the clash rule. Both must be present: the
    declared Cub Foods row and the exclusion that stops research replacing
    it with a customer count."""
    import json
    for root in (pathlib.Path("/app"),
                 pathlib.Path(__file__).resolve().parents[1]):
        f = root / "samples" / "companies.json"
        if f.exists():
            break
    else:
        pytest.skip("spec not present")
    unfi = next(c for c in json.loads(f.read_text("utf-8"))["companies"]
                if c["slug"] == "unfi")
    assert any(r["archetype"] == "STORE" for r in unfi.get("excluded") or [])
    assert any(r["archetype"] == "STORE"
               for r in unfi["declared_footprint"]), (
        "the Cub Foods stores UNFI does operate must survive the exclusion")


# ------------------------------------------- what promotion refused

def test_the_manifest_carries_promotion_declines(driver):
    """A decline is a decision about evidence and has to be as visible as an
    acceptance.

    The manifest recorded {promoted, detail} and dropped the rest, so a
    candidate research found and promotion refused left no trace. Boots is
    the case: research returned 2,164 GB stores, no GB/STORE row reached the
    footprint, and nothing in the artifact said whether that was a conflict,
    a duplicate or a bug.
    """
    rec = driver._promotion_record({
        "promoted": True, "ids": ["a", "b", "c"],
        "result": {"promoted_footprint": [{"country": "IE"}],
                   "declined": [{"candidate_id": "b",
                                 "reason": "sources disagree by 31%"}]}})
    assert rec["offered"] == 3
    assert rec["accepted"] == 1
    assert rec["declined_count"] == 1
    assert "disagree" in rec["declined"][0]["reason"]


def test_a_promotion_that_returned_nothing_is_not_an_error(driver):
    """A company with no footprint candidates records zeroes, not a crash."""
    rec = driver._promotion_record({"promoted": False,
                                    "detail": "no footprint candidates"})
    assert rec["offered"] == 0 and rec["declined_count"] == 0
    assert rec["detail"] == "no footprint candidates"
