"""One mine counted twice under two archetypes must be flagged.

Anglo American declared its Quellaveco copper mine as REMOTE_SITE and
research promoted the same mine as PLANT. The merge keys on (country,
archetype), so it added the second instead of reconciling it: the estate
held Quellaveco twice. archetype_collisions knew three pairs, all retail -
STORE/BRANCH, STORE/SERVICE_POINT, STORE/WAREHOUSE - and saw nothing.
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
    spec = importlib.util.spec_from_file_location("_chk_mine", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(tmp_path, *, declared, promoted):
    out = tmp_path / "out" / "miner"
    out.mkdir(parents=True)
    (out / "research.json").write_text(json.dumps({
        "evidenced_footprint": [{"country": c, "archetype": a, "sites": n}
                                for c, a, n in promoted]}), encoding="utf-8")
    spec = tmp_path / "companies.json"
    spec.write_text(json.dumps({"companies": [{
        "slug": "miner", "legal_name": "Miner",
        "declared_footprint": [{"country": c, "archetype": a, "sites": n}
                               for c, a, n in declared]}]}), encoding="utf-8")
    return tmp_path / "out", spec


def test_quellaveco_is_flagged(tmp_path):
    mod = _checker()
    out, spec = _case(tmp_path, declared=[("PE", "REMOTE_SITE", 1)],
                      promoted=[("PE", "PLANT", 1)])
    hits = mod.archetype_collisions(out, spec)
    assert [(h["country"], h["archetype"], h["declared_as"]) for h in hits] \
        == [("PE", "PLANT", "REMOTE_SITE")]


def test_the_corrected_declaration_is_not_flagged(tmp_path):
    """Declared PLANT, promoted PLANT: an ordinary merge, not a collision."""
    mod = _checker()
    out, spec = _case(tmp_path, declared=[("PE", "PLANT", 1)],
                      promoted=[("PE", "PLANT", 1)])
    assert mod.archetype_collisions(out, spec) == []


def test_the_retail_pairs_still_work(tmp_path):
    """Adding a pair must not have displaced the ones already there."""
    mod = _checker()
    out, spec = _case(tmp_path, declared=[("US", "BRANCH", 230)],
                      promoted=[("US", "STORE", 222)])
    assert len(mod.archetype_collisions(out, spec)) == 1
