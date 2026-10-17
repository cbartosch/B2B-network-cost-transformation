"""Research that found a figure the estate never used must be reported.

An apportioned declaration is only TESTED when research promotes a competing
figure. A pair that research found and did NOT promote leaves a round number
standing with nothing against it, which is how four of them survived a full
run: Carrefour Brazil declared at an apportioned 1,000 while research held
718 with a format breakdown reconciling exactly, and Capgemini's French,
German and British office counts in the same shape.

All four were eventually caught by priced_above_research, which reports a
GAP rather than a conflict - a weaker signal than the evidence deserved, and
one that fires only when the declaration happens to sit above what promoted.
"""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _checker():
    f = ROOT / "tools" / "check_footprint_verification.py"
    if not f.exists():
        pytest.skip("checker not present in this image")
    spec = importlib.util.spec_from_file_location("_chk_unused", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture(tmp_path, *, promoted, quantities, declared, excluded=()):
    """promoted/declared are (country, archetype, sites) triples.

    Deliberately NOT dicts keyed on a (country, archetype) tuple:
    test_integrity.test_every_prior_key_carries_a_bandwidth scans every
    source file for that literal shape, because a two-string tuple key is
    how a rate-card entry silently loses its bandwidth. The guard cannot
    tell a test fixture from a price table and should not try.
    """
    out = tmp_path / "out"
    (out / "acme").mkdir(parents=True)
    (out / "acme" / "research.json").write_text(json.dumps({
        "evidenced_footprint": [
            {"country": c, "archetype": a, "sites": n}
            for c, a, n in promoted],
        "dispositions": [{"domain_no": 2, "evidence": {
            "quantities": quantities}}],
    }), encoding="utf-8")
    spec = tmp_path / "companies.json"
    spec.write_text(json.dumps({"companies": [{
        "slug": "acme", "legal_name": "Acme",
        "declared_footprint": [
            {"country": c, "archetype": a, "sites": n}
            for c, a, n in declared],
        "excluded": [{"country": c, "archetype": a, "reason": "x"}
                     for c, a in excluded],
    }]}), encoding="utf-8")
    return out, spec


def test_a_figure_research_found_and_never_promoted_is_reported(tmp_path):
    """carrefour BR/STORE: 718 found, 1,000 declared, nothing promoted."""
    mod = _checker()
    out, spec = _fixture(
        tmp_path,
        promoted=[],
        quantities=[{"label": "STORE - Brazil stores, all formats",
                     "country": "BR", "value": 718, "unit": "stores"}],
        declared=[("BR", "STORE", 1000)])
    rows = mod.found_but_unused(out, spec)
    assert len(rows) == 1
    assert rows[0]["found"] == 718
    assert rows[0]["declared"] == 1000


def test_a_promoted_pair_is_not_reported(tmp_path):
    """The estate used it. Nothing to say."""
    mod = _checker()
    out, spec = _fixture(
        tmp_path,
        promoted=[("BR", "STORE", 718)],
        quantities=[{"label": "STORE - Brazil stores", "country": "BR",
                     "value": 718, "unit": "stores"}],
        declared=[("BR", "STORE", 1000)])
    assert mod.found_but_unused(out, spec) == []


def test_a_deliberately_excluded_pair_is_not_reported(tmp_path):
    """An analyst ruled on it. Re-reporting it is noise, not a finding."""
    mod = _checker()
    out, spec = _fixture(
        tmp_path,
        promoted=[],
        quantities=[{"label": "STORE - dealership network", "country": "IN",
                     "value": 587, "unit": "stores"}],
        declared=[("IN", "STORE", 0)],
        excluded=[("IN", "STORE")])
    assert mod.found_but_unused(out, spec) == []


def test_the_largest_value_wins_for_a_pair(tmp_path):
    """Several findings per pair is normal; the report names the biggest,
    because that is the one most likely to contradict a declaration."""
    mod = _checker()
    out, spec = _fixture(
        tmp_path,
        promoted=[],
        quantities=[
            {"label": "STORE - Brazil", "country": "BR", "value": 400},
            {"label": "STORE - Brazil all formats", "country": "BR",
             "value": 718},
        ],
        declared=[("BR", "STORE", 1000)])
    rows = mod.found_but_unused(out, spec)
    assert [r["found"] for r in rows] == [718]


def test_a_label_that_merely_mentions_an_archetype_is_not_a_count(tmp_path):
    """The checker reads only the LEADING token, deliberately. 'circuits per
    STORE' is not a count of stores."""
    mod = _checker()
    out, spec = _fixture(
        tmp_path,
        promoted=[],
        quantities=[{"label": "Access circuits per STORE", "country": "BR",
                     "value": 2}],
        declared=[("BR", "STORE", 1000)])
    assert mod.found_but_unused(out, spec) == []


def test_the_verifier_archetype_list_matches_the_spec():
    """A copied list that nothing compares is a list that drifts.

    The drift is silent: a missing archetype does not raise, it just stops
    reporting rows of that type. The previous copy held five of fifteen.
    """
    mod = _checker()
    spec = json.loads((ROOT / "samples" / "companies.json")
                      .read_text("utf-8"))
    used = {r["archetype"] for c in spec["companies"]
            for r in c["declared_footprint"]}
    missing = used - set(mod.VALID_ARCHETYPES)
    assert not missing, f"the checker does not know these archetypes: {missing}"
