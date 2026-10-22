"""A VERIFIED register entry vouches for a figure, not for a pair.

The register covered its (company, country, archetype) pair, so whatever
figure the pair held next was covered too. Network Rail's GB/TERMINAL was
verified at 20 - the stations it manages directly - and a later run promoted
2,593, the whole GB network including stations the train operators run. The
checker filed 2,593 under "verified" on the strength of a verdict about 20,
and --strict passed it.
"""
import csv
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELDS = ["slug", "country", "archetype", "declared_sites", "register_sites",
          "disposition", "as_of", "site_definition", "evidence_ref",
          "verified_by", "verified_at", "note"]


def _checker():
    f = ROOT / "tools" / "check_footprint_verification.py"
    if not f.exists():
        pytest.skip("checker not present in this image")
    spec = importlib.util.spec_from_file_location("_chk_figure", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strict(tmp_path, monkeypatch, *, used, verified, disposition="VERIFIED"):
    out = tmp_path / "out" / "railway"
    out.mkdir(parents=True)
    (out / "research.json").write_text(json.dumps({
        "evidenced_footprint": [{"country": "GB", "archetype": "TERMINAL",
                                 "sites": used, "as_of": "2024-03-31",
                                 "source_count": 2}],
        "dispositions": []}), encoding="utf-8")
    # changes() reads what the estate USED from the manifest, not research.
    (out / "manifest.json").write_text(json.dumps({
        "footprint_used": [{"country": "GB", "archetype": "TERMINAL",
                            "sites": used}],
        "footprint_provenance": []}), encoding="utf-8")
    spec = tmp_path / "companies.json"
    spec.write_text(json.dumps({"companies": [{
        "slug": "railway", "legal_name": "Railway",
        "declared_footprint": [{"country": "GB", "archetype": "TERMINAL",
                                "sites": 0}]}]}), encoding="utf-8")
    reg = tmp_path / "register.csv"
    with reg.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerow({"slug": "railway", "country": "GB", "archetype": "TERMINAL",
                    "declared_sites": 0, "register_sites": verified,
                    "disposition": disposition, "as_of": "2024-03-31",
                    "site_definition": "stations it manages directly",
                    "evidence_ref": "x", "verified_by": "x",
                    "verified_at": "2026-10-16", "note": "x"})
    mod = _checker()
    monkeypatch.setattr(sys, "argv", [
        "check", "--strict", "--out", str(tmp_path / "out"),
        "--spec", str(spec), "--register", str(reg)])
    return mod.main()


def test_a_verdict_about_20_does_not_cover_2593(tmp_path, monkeypatch, capsys):
    assert _strict(tmp_path, monkeypatch, used=2593, verified=20) == 1
    shown = capsys.readouterr().out
    assert "verified, but not this figure" in shown
    assert "RE-VERIFY" in shown


def test_the_verified_figure_still_covers_itself(tmp_path, monkeypatch):
    assert _strict(tmp_path, monkeypatch, used=20, verified=20) == 0


def test_an_excluded_figure_is_a_different_claim(tmp_path, monkeypatch):
    """EXCLUDED records a figure kept OUT, so it is not expected to match
    what the estate holds - only VERIFIED makes that claim."""
    assert _strict(tmp_path, monkeypatch, used=20, verified=2593,
                   disposition="EXCLUDED") == 0


def test_an_excluded_research_figure_does_not_unverify_a_pair(tmp_path,
                                                             monkeypatch):
    """Declaring the right figure and excluding research's wrong one is how a
    pair is corrected. The EXCLUDED record carries research's figure as its
    'used', and a VERIFIED entry must not be held to the number it was
    written to keep out."""
    out = tmp_path / "out" / "post"
    out.mkdir(parents=True)
    (out / "research.json").write_text(json.dumps({
        "evidenced_footprint": [], "dispositions": []}), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "footprint_used": [{"country": "DE", "archetype": "TERMINAL",
                            "sites": 165}],
        "footprint_provenance": [{"country": "DE", "archetype": "TERMINAL",
                                  "sites": 81,
                                  "origin": "EXCLUDED_BY_SCOPE"}]}),
        encoding="utf-8")
    spec = tmp_path / "companies.json"
    spec.write_text(json.dumps({"companies": [{
        "slug": "post", "legal_name": "Post",
        "declared_footprint": [{"country": "DE", "archetype": "TERMINAL",
                                "sites": 165}],
        "excluded": [{"country": "DE", "archetype": "TERMINAL",
                      "reason": "x"}]}]}), encoding="utf-8")
    reg = tmp_path / "register.csv"
    with reg.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerow({"slug": "post", "country": "DE", "archetype": "TERMINAL",
                    "declared_sites": 165, "register_sites": 165,
                    "disposition": "VERIFIED", "as_of": "2025-12-31",
                    "site_definition": "mail, parcel and freight centres",
                    "evidence_ref": "x", "verified_by": "x",
                    "verified_at": "2026-10-22", "note": "x"})
    mod = _checker()
    monkeypatch.setattr(sys, "argv", [
        "check", "--strict", "--out", str(tmp_path / "out"),
        "--spec", str(spec), "--register", str(reg)])
    assert mod.main() == 0
