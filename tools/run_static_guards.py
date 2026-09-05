#!/usr/bin/env python3
"""Run the static guards trapped inside dependency-blocked test files.

31 cross-module guards sit in files that import sqlalchemy, fastapi or pydantic
for *other* tests in the same file. There is no CI workflow, so those guards run
nowhere at all - which is how LEV-MPLS-001 kept a dead vocabulary value through
a release whose whole purpose was to remove it.

A guard is static when it reads source and needs no fixture. Those need no
database; they only need the import at the top of the file to succeed. Shallow
stubs give them that, and every test that genuinely needs the real library
fails on use and is skipped rather than counted.
"""
import ast
import importlib.util
import pathlib
import signal
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "static_guard_results.txt"


def _stub(name):
    module = types.ModuleType(name)

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return self

        def __getattr__(self, _n):
            return _Any()

        def __or__(self, _o):
            return self

        def __getitem__(self, _k):
            return self

    module.__getattr__ = lambda _n: _Any()
    sys.modules[name] = module


for name in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc",
             "sqlalchemy.engine", "fastapi", "fastapi.testclient",
             "pydantic", "psycopg", "httpx"):
    _stub(name)

sys.path.insert(0, str(ROOT / "api_service"))
sys.path.insert(0, str(ROOT / "tests"))
exec((ROOT / "tools" / "run_tests_offline.py").read_text().split("def _importable")[0])


def _timeout(_s, _f):
    raise TimeoutError("guard did not finish")


signal.signal(signal.SIGALRM, _timeout)

lines = []
ran = passed = 0
for path in sorted((ROOT / "tests").glob("test_*.py")):
    source = path.read_text()
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:                                   # noqa: BLE001
        lines.append(f"SKIP {path.name}: import {type(exc).__name__}")
        continue

    for node in ast.parse(source).body:
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")):
            continue
        if node.args.args:                       # wants a fixture
            continue
        body = ast.unparse(node)
        if not ("read_text()" in body or "getsource" in body):
            continue
        if any(k in body for k in ("session", "insert(", "client.")):
            continue
        fn = getattr(module, node.name, None)
        if not callable(fn):
            continue
        ran += 1
        signal.alarm(3)
        try:
            fn()
            passed += 1
        except AssertionError as exc:
            lines.append(f"FAIL {path.name}::{node.name}\n     {str(exc)[:200]}")
        except Exception as exc:                               # noqa: BLE001
            lines.append(f"ERR  {path.name}::{node.name}: {type(exc).__name__}")
        finally:
            signal.alarm(0)

header = (f"{ran} static guard(s) executed, {passed} passed, "
          f"{ran - passed} not passing\n")
OUT.write_text(header + "\n".join(lines) + "\n")
print(header)
