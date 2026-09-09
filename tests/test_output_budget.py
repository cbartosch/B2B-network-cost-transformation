"""The output ceiling a call actually gets.

A live run failed closed with "entity.resolve.candidates was cut off at 4000
tokens". The governed budget is 8000, and `structured_call` had a hardcoded
default of 4000 that seven of its ten call sites took silently - so the policy
that exists to be tuned per engagement was unreachable from most of the system,
and raising the governed number would have changed nothing.

Read in the gateway rather than at each call site, on exactly the reasoning the
truncation check one function below already uses: research and the benchmark
ingest each grew their own lookup, and the seven that did not were the ones
being cut off.
"""
import ast
from pathlib import Path

import pytest


def _app():
    root = Path(__file__).resolve().parents[1]
    return next(c for c in (root / "api_service" / "app", root / "app")
                if (c / "llm").exists())


def _gateway_source():
    return (_app() / "llm" / "gateway.py").read_text()


def test_no_call_site_is_left_on_a_hardcoded_default():
    """The defect. Seven of ten passed nothing and got 4000."""
    source = _gateway_source()
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "structured_call")
    default = next(
        (ast.unparse(d) for a, d in zip(
            fn.args.kwonlyargs, fn.args.kw_defaults) if a.arg == "max_tokens"),
        None)
    assert default == "None", (
        "max_tokens must default to None so the gateway resolves the governed "
        "budget; a number here is a second ceiling that call sites take "
        "silently")


def test_the_fallback_is_the_governed_default_not_something_lower():
    """A call that falls back should behave like a governed one, not like a
    truncated one."""
    source = _gateway_source()
    assert "FALLBACK_MAX_TOKENS = 8000" in source


def test_the_budget_is_resolved_before_the_retry_loop():
    """A budget that changed between attempts would make the truncation
    message name a ceiling the failing attempt did not have."""
    source = ast.unparse(ast.parse(_gateway_source()))
    assert source.index("governed_max_tokens(session)") < source.index(
        "was cut off at")


def test_a_lookup_failure_never_fails_the_run():
    """An unreachable policy table is a reason to use the governed default,
    not a reason to abandon the call."""
    source = _gateway_source()
    block = source[source.index("def governed_max_tokens"):
                   source.index("def structured_call")]
    assert "except Exception" in block
    assert "return fallback" in block


def test_the_sweep_keeps_its_own_smaller_budget():
    """The per-class sweep is deliberately 6000, not the per-call 8000: one
    agent call per fact class was the 4.147 fix, and a larger budget there
    would invite the five-classes-at-once reply it replaced."""
    app = _app()
    seed = (app / "seed.py").read_text()
    assert '"max_output_tokens_per_sweep_call", "6000"' in seed
    assert '"max_output_tokens_per_call", "8000"' in seed
    known = (app / "domain" / "known_facts.py").read_text()
    assert "_sweep_budget(session)" in known


def test_no_module_hardcodes_an_output_budget_of_its_own():
    """benchmark_ingest carried its own default of 8000 - the right number in
    a second place, which is a number that drifts the moment the policy is
    tuned."""
    app = _app()
    offenders = []
    for path in list((app / "domain").glob("*.py")) + [app / "llm" / "gateway.py"]:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef):
                continue
            for arg, default in zip(node.args.kwonlyargs + node.args.args[::-1],
                                    (node.args.kw_defaults
                                     + list(node.args.defaults))):
                if (arg.arg == "max_tokens" and default is not None
                        and isinstance(default, ast.Constant)
                        and default.value is not None):
                    offenders.append(f"{path.name}::{node.name}")
    assert not offenders, (
        f"{offenders} hardcode an output budget; None defers to the governed "
        f"one")


@pytest.mark.parametrize("stored,expected", [
    ("8000", 8000), ("12000", 12000), ("2000", 2000),
    (None, 8000), ("lots", 8000), ("", 8000),
])
def test_a_tuned_row_is_honoured_and_anything_unusable_falls_back(
        stored, expected):
    """The whole point: an engagement that needs a larger ceiling changes the
    row, not the code."""
    import types

    from app.llm import gateway

    class _Row:
        def __init__(self, value):
            self.value = value

    class _Session:
        def execute(self, *a, **k):
            row = None if stored is None else _Row(stored)
            return types.SimpleNamespace(first=lambda: row)

    assert gateway.governed_max_tokens(_Session()) == expected
