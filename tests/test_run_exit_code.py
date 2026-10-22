"""A run that failed companies must not exit 0.

The driver printed "completed 1, failed 8" after a DNS outage took out eight
of nine companies, and exited 0. Earlier the same day a run that could not
open its own file - Git Bash had rewritten the path - also exited 0. The
outage handling inside the run was right both times; the one bit of the
result a script can actually check said everything was fine.
"""
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _driver():
    f = ROOT / "tools" / "run_samples.py"
    if not f.exists():
        pytest.skip("driver not present in this image")
    spec = importlib.util.spec_from_file_location("_rs_exit", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, monkeypatch, tmp_path, fail_slugs):
    spec = tmp_path / "companies.json"
    spec.write_text(json.dumps({"companies": [
        {"slug": s, "legal_name": s, "declared_footprint": []}
        for s in ("a", "b", "c")]}), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    def fake_run_one(spec, *a, **k):
        if spec["slug"] in fail_slugs:
            raise RuntimeError("research never reached the provider")
        return {"slug": spec["slug"]}

    monkeypatch.setattr(mod, "run_one", fake_run_one)
    monkeypatch.setattr(mod, "resolve_spec", lambda explicit, outdir: spec)
    monkeypatch.setattr(sys, "argv", ["run_samples.py", "--spec", str(spec),
                                      "--out", str(out)])
    return mod.main()


def test_a_run_with_failures_exits_nonzero(monkeypatch, tmp_path):
    mod = _driver()
    assert _run(mod, monkeypatch, tmp_path, fail_slugs={"b", "c"}) == 1


def test_a_clean_run_exits_zero(monkeypatch, tmp_path):
    mod = _driver()
    assert _run(mod, monkeypatch, tmp_path, fail_slugs=set()) == 0
