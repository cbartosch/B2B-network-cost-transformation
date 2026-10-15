"""BENCHMARK_PRIOR must not be written over a domain an agent answered.

`dispose_analyst_domains` disposes everything the run will not research,
because V0 refuses to publish while any of the 24 domains is undisposed.
On a fresh case that is right. On a RESUMED case it is a way to delete
paid research: the PUT is a whole-case replacement, and a domain omitted
from --domains looks exactly like a domain with no agent behind it.

The function's own docstring already recorded losing two researched
domains this way. It then happened again and larger: a --redo run asking
for domain 19 alone disposed the other twenty-three on three companies,
destroying forty-eight agent verdicts with their evidence blobs before
the new research started. The log said "disposed 23 domain(s)" and
nothing said what twenty-three meant.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _driver():
    f = ROOT / "tools" / "run_samples.py"
    if not f.exists():
        pytest.skip("driver not present in this image")
    spec = importlib.util.spec_from_file_location("_rs", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _disposed(mod, monkeypatch, researching, keep):
    """The domain numbers the PUT would actually overwrite."""
    sent = {}

    def fake_call(method, path, body=None, timeout=None):
        sent["payload"] = body
        return 200, {}

    monkeypatch.setattr(mod, "call", fake_call)
    mod.dispose_analyst_domains("case-1", "acme", researching, keep=keep)
    return sorted(r["domain_no"] for r in sent["payload"])


def test_a_researched_domain_is_never_disposed(monkeypatch):
    """The exact shape of the loss: --domains 19 on a case holding 17."""
    mod = _driver()
    held = {1, 2, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22}
    disposed = _disposed(mod, monkeypatch, researching=[19], keep=held)
    assert not (set(disposed) & held), (
        f"would overwrite agent verdicts on {sorted(set(disposed) & held)}")


def test_the_domains_nobody_researches_are_still_disposed(monkeypatch):
    """V0 refuses to publish while any of the 24 is undisposed, so the
    seven with no agent must still be written."""
    mod = _driver()
    held = {1, 2, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22}
    disposed = _disposed(mod, monkeypatch, researching=[19], keep=held)
    assert set(disposed) == {3, 4, 5, 11, 17, 23, 24}


def test_a_fresh_case_is_unchanged(monkeypatch):
    """keep is empty on a first run and the old behaviour stands: every
    domain this run will not research is disposed."""
    mod = _driver()
    disposed = _disposed(mod, monkeypatch, researching=mod.AGENT_DOMAINS,
                         keep=set())
    assert set(disposed) == set(mod.ANALYST_DOMAINS)


def test_the_call_site_passes_what_the_case_already_holds():
    """The guard is only worth having if the driver supplies it."""
    src = (ROOT / "tools" / "run_samples.py").read_text(encoding="utf-8")
    assert "keep=done_before" in src
