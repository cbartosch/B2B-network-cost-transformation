#!/usr/bin/env python3
"""Run whatever part of the suite this environment can execute, without pytest.

**This is a fallback, not a replacement for pytest.** Where pytest is available,
`make test-all` is the real gate: it collects fixtures, isolates state, and runs
the 28 files this cannot reach. Use this when there is no package index -
in a locked-down container, an air-gapped review, or an audit sandbox - because
334 tests that run are worth more than 901 that do not.

The mandate that produced it forbids reporting an unexecuted test as passed. For
most of this project's life the whole suite was in that category: written,
counted in release notes, and never once executed. A 90-line shim supplying
`parametrize`, `raises` and `importorskip` was the difference between executing
nothing and executing the structural suite - and the first run found 24
failures.

What it cannot do:

- build fixtures. A test taking arguments it cannot supply is recorded skipped,
  never passed.
- reach sqlalchemy, fastapi or pydantic. Those files are reported blocked with
  the module that blocks them.
- isolate state between tests. Order-dependent failures will look real here and
  may not be.


The audit mandate forbids reporting an unexecuted test as passed, and requires
the precise reason any procedure is blocked. This establishes both.

`pip install` cannot reach an index here, so pytest is absent - and pytest is
absent for one reason: 38 of 39 test files import it, almost always only for
`parametrize` and `raises`. A shim supplying those two things unlocks every
test whose *other* imports are satisfiable, which is the difference between
executing nothing and executing the structural suite.

Files needing sqlalchemy, fastapi or pydantic remain blocked and are reported
as such. This runner does not modify the bundle; it lives in the audit
workspace and imports from it read-only.
"""
import ast
import importlib.util
import pathlib
import sys
import traceback
import types

BUNDLE = pathlib.Path(__file__).resolve().parents[1]
TESTS = BUNDLE / "tests"


# --------------------------------------------------------- the pytest shim
class _Raises:
    def __init__(self, expected, match=None):
        self.expected, self.match = expected, match

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"expected {self.expected} and none raised")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match:
            import re
            if not re.search(self.match, str(exc)):
                raise AssertionError(
                    f"{exc!r} does not match {self.match!r}")
        return True


class _Mark:
    def parametrize(self, argnames, argvalues, **kw):
        names = ([a.strip() for a in argnames.split(",")]
                 if isinstance(argnames, str) else list(argnames))

        def decorate(fn):
            fn._params = (names, list(argvalues))
            return fn
        return decorate

    def __getattr__(self, _name):
        def decorate(fn=None, **kw):
            return fn if fn is not None else (lambda f: f)
        return decorate


def _fixture(*a, **kw):
    def decorate(fn):
        fn._is_fixture = True
        return fn
    return decorate(a[0]) if a and callable(a[0]) else decorate


def _skip(reason=""):
    raise _Skipped(reason)


class _Skipped(Exception):
    pass


shim = types.ModuleType("pytest")
shim.raises = _Raises
shim.mark = _Mark()
shim.fixture = _fixture
shim.skip = _skip
shim.approx = lambda v, **kw: v


def _importorskip(name, **kw):
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        raise _Skipped(f"{name} not installed")


shim.importorskip = _importorskip
shim.fail = lambda msg="": (_ for _ in ()).throw(AssertionError(msg))
sys.modules.setdefault("pytest", shim)

sys.path.insert(0, str(BUNDLE / "api_service"))
sys.path.insert(0, str(TESTS))


def _importable(path: pathlib.Path) -> tuple:
    """Can this file's imports be satisfied here? Returns (ok, missing)."""
    missing = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module.split(".")[0]]
        for name in names:
            if name in ("pytest", "app", "conftest"):
                continue
            if importlib.util.find_spec(name) is None:
                missing.add(name)
    return (not missing), sorted(missing)


def main() -> int:
    results = {"passed": [], "failed": [], "errored": [], "skipped": [],
               "blocked": {}, "blocked_tests": []}

    for path in sorted(TESTS.glob("test_*.py")):
        ok, missing = _importable(path)
        if not ok:
            results["blocked"][path.name] = missing
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:                       # noqa: BLE001
            results["blocked"][path.name] = [f"import failed: {exc}"]
            continue

        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            fn = getattr(module, name)
            if not callable(fn):
                continue
            argcount = fn.__code__.co_argcount
            params = getattr(fn, "_params", None)
            cases = ([dict(zip(params[0], v if isinstance(v, tuple) else (v,)))
                      for v in params[1]] if params else [{}])
            for case in cases:
                # A test wanting a fixture this runner cannot build is
                # recorded as skipped, not as passed.
                if argcount > len(case):
                    results["skipped"].append(f"{path.name}::{name} "
                                              f"(needs a fixture)")
                    break
                label = f"{path.name}::{name}" + (f"[{case}]" if case else "")
                try:
                    fn(**case)
                    results["passed"].append(label)
                except AssertionError as exc:
                    results["failed"].append((label, str(exc)[:400]))
                except _Skipped:
                    results["skipped"].append(label)
                except ModuleNotFoundError as exc:
                    # A dependency imported inside the test body. Blocked, not
                    # errored: reporting it as a defect would inflate the
                    # failure count with this environment's limits.
                    results["blocked_tests"].append((label, str(exc)))
                except Exception:                      # noqa: BLE001
                    results["errored"].append(
                        (label, traceback.format_exc(limit=2)[-400:]))

    print("EXECUTED TEST RESULTS")
    print(f"  passed   {len(results['passed'])}")
    print(f"  failed   {len(results['failed'])}")
    print(f"  errored  {len(results['errored'])}")
    print(f"  skipped  {len(results['skipped'])}")
    print(f"  blocked  {len(results['blocked'])} file(s), "
          f"{len(results['blocked_tests'])} test(s) on a deferred import")

    if results["failed"]:
        print("\nFAILURES")
        for label, message in results["failed"]:
            print(f"  {label}")
            first = next((l for l in message.splitlines() if l.strip()),
                         "(assertion with no message)")
            print(f"     {first[:180]}")
    if results["errored"]:
        print("\nERRORS")
        for label, message in results["errored"][:10]:
            print(f"  {label}")
            print(f"     {message.strip().splitlines()[-1][:180]}")

    print("\nBLOCKED FILES AND THEIR MISSING DEPENDENCIES")
    from collections import Counter
    counter = Counter(m for v in results["blocked"].values() for m in v)
    for module, count in counter.most_common():
        print(f"  {module:52} blocks {count} file(s)")

    return 1 if results["failed"] or results["errored"] else 0


if __name__ == "__main__":
    sys.exit(main())
