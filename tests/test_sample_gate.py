"""The gate that decides whether a sample set may be committed.

Tested because the first version of it was not. That one asked only
"more than zero researched domains?" and passed a repair which had produced
four of seventeen and two of seventeen - 98 of its 106 agent runs had failed
against an unreachable provider. An untested gate reads as verification and
is decoration.
"""
import csv
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = next((c for c in (ROOT / "tools" / "check_samples.py",
                         ROOT / "check_samples.py") if c.exists()), None)

pytestmark = pytest.mark.skipif(
    TOOL is None, reason="tools/ is not present in this image")


def _write(root: pathlib.Path, companies: dict):
    """A minimal set: summary.csv plus one manifest per company."""
    root.mkdir(parents=True, exist_ok=True)
    cols = ["slug", "company", "sites", "footprint_origin", "baseline_base",
            "domains_researched"]
    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for slug, c in companies.items():
            w.writerow({"slug": slug, "company": slug.title(),
                        "sites": c["sites"],
                        "footprint_origin": "PUBLIC_DISCLOSURE_ONLY",
                        "baseline_base": c.get("baseline", "1000.00"),
                        "domains_researched": c["researched"]})
    for slug, c in companies.items():
        d = root / slug
        d.mkdir(exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({
            "slug": slug,
            "footprint_used": [{"country": "DE", "archetype": "PLANT",
                                "sites": c.get("manifest_sites", c["sites"])}],
        }), encoding="utf-8")


def _run(out, baseline=None, repaired=""):
    cmd = [sys.executable, str(TOOL), "--out", str(out)]
    if baseline:
        cmd += ["--baseline", str(baseline)]
    if repaired:
        cmd += ["--repaired", repaired]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout


HEALTHY = {"tesco": {"sites": 3908, "researched": 16},
           "lufthansa": {"sites": 213, "researched": 15}}


def test_a_healthy_set_passes(tmp_path):
    _write(tmp_path / "out", HEALTHY)
    rc, out = _run(tmp_path / "out", repaired="lufthansa")
    assert rc == 0, out
    assert "gate passed" in out


def test_a_repair_that_did_not_take_is_refused(tmp_path):
    """Four of seventeen is the number that got through last time."""
    companies = {**HEALTHY, "lufthansa": {"sites": 213, "researched": 4}}
    _write(tmp_path / "out", companies)
    rc, out = _run(tmp_path / "out", repaired="lufthansa")
    assert rc == 1
    assert "below the floor" in out


def test_more_than_nothing_is_not_enough(tmp_path):
    """The exact hole in the first gate: non-zero, and nowhere near done."""
    companies = {**HEALTHY, "lufthansa": {"sites": 213, "researched": 1}}
    _write(tmp_path / "out", companies)
    rc, _ = _run(tmp_path / "out", repaired="lufthansa")
    assert rc == 1


def test_a_company_may_not_go_backwards(tmp_path):
    """An outage depresses research, and a re-run that lands lower than the
    committed set is a worse set however it reads alone."""
    _write(tmp_path / "base", HEALTHY)
    _write(tmp_path / "out", {**HEALTHY,
                              "tesco": {"sites": 3908, "researched": 9}})
    rc, out = _run(tmp_path / "out", baseline=tmp_path / "base")
    assert rc == 1
    assert "regression against the committed set" in out


def test_an_improvement_is_reported_and_allowed(tmp_path):
    _write(tmp_path / "base", {**HEALTHY,
                               "lufthansa": {"sites": 213, "researched": 4}})
    _write(tmp_path / "out", HEALTHY)
    rc, out = _run(tmp_path / "out", baseline=tmp_path / "base",
                   repaired="lufthansa")
    assert rc == 0, out
    assert "improved: lufthansa: 4 -> 15" in out


def test_a_summary_that_disagrees_with_its_manifest_is_refused(tmp_path):
    """The check that would have caught a footprint the merge shrank."""
    _write(tmp_path / "out", {**HEALTHY,
                              "tesco": {"sites": 3908, "researched": 16,
                                        "manifest_sites": 1}})
    rc, out = _run(tmp_path / "out")
    assert rc == 1
    assert "manifest says 1" in out


def test_an_empty_estate_is_refused(tmp_path):
    _write(tmp_path / "out", {**HEALTHY,
                              "tesco": {"sites": 0, "researched": 16}})
    rc, out = _run(tmp_path / "out")
    assert rc == 1
    assert "empty estate" in out


def test_a_company_with_no_manifest_is_refused(tmp_path):
    _write(tmp_path / "out", HEALTHY)
    (tmp_path / "out" / "tesco" / "manifest.json").unlink()
    rc, out = _run(tmp_path / "out")
    assert rc == 1
    assert "no manifest" in out


def test_the_floor_applies_only_to_what_was_repaired(tmp_path):
    """A company nobody claimed to repair is not held to the floor - the set
    carries companies whose research legitimately found less."""
    companies = {**HEALTHY, "unilever": {"sites": 43, "researched": 2}}
    _write(tmp_path / "out", companies)
    rc, out = _run(tmp_path / "out", repaired="lufthansa")
    assert rc == 0, out
