"""A domain the provider was never reached for must not be disposed.

BENCHMARK_PRIOR with "research returned no verdict" asserts something
specific: research ran, and nothing could be established. A domain whose
call died in DNS establishes nothing about anything, and recording it the
same way turns an outage into a finding.

It has now happened twice. The first time cost a twenty-company run most
of its research and is written into DomainResult's own comments - which is
why `failure_kind` and `retryable` exist at all. The second time cost
Fraport twelve of its seventeen domains:

    FAILED  581.7s  ProviderUnavailable: Server disconnected ...
    FAILED    0.2s  ProviderUnavailable: [Errno -2] Name or service not known
    ... eleven more, then DNS recovered and domains 18-22 ran normally

The run reported "completed 41, failed 0" and published an estimate whose
footprint basis was PUBLIC_DISCLOSURE_ONLY. The API knew: every one of
those results carried failure_kind=PROVIDER_UNAVAILABLE and retryable=True.
The driver read neither.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _driver():
    f = ROOT / "tools" / "run_samples.py"
    if not f.exists():
        pytest.skip("driver not present in this image")
    spec = importlib.util.spec_from_file_location("_rs_outage", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _result(**kw):
    base = {"domain_no": 2, "disposition": None, "failed": False,
            "failure_kind": None, "retryable": None, "failure_detail": None}
    base.update(kw)
    return {"status": 200, "seconds": 0.2, "result": {"results": [base]}}


def test_a_transport_failure_is_reported_as_blocked():
    mod = _driver()
    raw = {2: _result(failed=True, failure_kind="PROVIDER_UNAVAILABLE",
                      retryable=True)}
    assert mod.transport_blocked(raw) == {2: "PROVIDER_UNAVAILABLE"}


def test_every_retryable_failure_kind_blocks():
    """Three of the five kinds are infrastructure. All three must block."""
    mod = _driver()
    from app.domain import research

    infra = [k for k, retry in research.FAILURE_KINDS.items() if retry]
    assert infra, "no retryable failure kinds are declared"
    for kind in infra:
        raw = {7: _result(failed=True, failure_kind=kind, retryable=True)}
        assert mod.transport_blocked(raw) == {7: kind}, kind


def test_a_bad_answer_does_not_block():
    """OUTPUT_INVALID is the model answering badly, which retrying will not
    fix. That is a research outcome and the fallback should cover it."""
    mod = _driver()
    raw = {2: _result(failed=True, failure_kind="OUTPUT_INVALID",
                      retryable=False)}
    assert mod.transport_blocked(raw) == {}


def test_a_domain_with_no_verdict_does_not_block():
    """The agent ran and had nothing to say. BENCHMARK_PRIOR is honest here."""
    mod = _driver()
    assert mod.transport_blocked({2: _result()}) == {}


def test_blocked_domains_are_never_disposed(monkeypatch):
    """The whole point: a blocked domain must not reach the PUT payload."""
    mod = _driver()
    sent = {}

    def fake_call(method, path, body=None, timeout=None):
        sent["payload"] = body
        return 200, {}

    class _Row:
        def __init__(self, n):
            self.domain_no = n

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _q):
            # Domains 18-22 survived the outage; nothing else is disposed.
            class _R:
                def all(_s):
                    return [_Row(n) for n in (18, 19, 20, 21, 22)]
            return _R()

    monkeypatch.setattr(mod, "call", fake_call)
    monkeypatch.setattr(mod.db, "SessionLocal", lambda: _Session())

    blocked = {n: "PROVIDER_UNAVAILABLE"
               for n in (1, 2, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16)}
    out = mod.dispose_unanswered("case-1", "fraport", blocked=blocked)

    disposed = {r["domain_no"] for r in (sent.get("payload") or [])}
    assert not (disposed & set(blocked)), (
        f"disposed {sorted(disposed & set(blocked))}, which never reached "
        f"the provider")
    assert out["blocked"] == blocked
    # The analyst domains with no agent still fall back, as they always did.
    assert disposed, "the fallback stopped covering genuinely unasked domains"


def test_without_blocked_the_fallback_is_unchanged(monkeypatch):
    """The safety net still exists. Omitting `blocked` must behave exactly as
    before, or every caller that does not pass it loses its estimate."""
    mod = _driver()
    sent = {}

    def fake_call(method, path, body=None, timeout=None):
        sent["payload"] = body
        return 200, {}

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _q):
            class _R:
                def all(_s):
                    return []
            return _R()

    monkeypatch.setattr(mod, "call", fake_call)
    monkeypatch.setattr(mod.db, "SessionLocal", lambda: _Session())

    out = mod.dispose_unanswered("case-1", "slug")
    assert out["fell_back"], "the fallback disposed nothing at all"
    assert all(r["disposition"] == "BENCHMARK_PRIOR"
               for r in sent["payload"])
