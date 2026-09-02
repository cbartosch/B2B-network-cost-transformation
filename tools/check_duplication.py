#!/usr/bin/env python3
"""Seven shapes duplication has taken in this codebase, checked in one pass.

Written after an external audit found what six weeks of my own reading had not:
the same feature built twice, then a partial cleanup that left five artefacts of
the first implementation behind. Each check below corresponds to an instance that
actually occurred, not a hypothetical:

  same-module names        two EstimateAnswer classes, two estimate_answer gates,
                           two ClearRightsIn models, two _migrate_v21 steps
  cross-module exports     domain/explain.py and domain/estimate_qa.py
  verb+path                two handlers on POST estimates:ask
  test names               the same test name in two files
  migration columns        a second step adding a column already added
  class across modules     a schema defined in two places
  panel headings           two "Ask about this estimate" panels

Python does not error on any of them. It keeps the last definition and runs, so
a duplicate is a working module in which something earlier has been silently
replaced. `make check-duplication`, exit code gates a build.
"""
import ast
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
UI = ROOT / "analyst_ui" / "streamlit_app"
TESTS = ROOT / "tests"


def same_module_names():
    found = []
    for path in sorted(APP.rglob("*.py")):
        seen = defaultdict(list)
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                seen[node.name].append(node.lineno)
        found += [f"{path.name}: {n} at {ls}" for n, ls in seen.items() if len(ls) > 1]
    return found


def cross_module_exports():
    exports = {}
    for path in sorted((APP / "domain").glob("*.py")):
        names = {n.name for n in ast.parse(path.read_text()).body
                 if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
        if len(names) >= 2:
            exports[path.name] = names
    found, modules = [], sorted(exports)
    for i, first in enumerate(modules):
        for second in modules[i + 1:]:
            shared = exports[first] & exports[second]
            smaller = min(len(exports[first]), len(exports[second]))
            if shared and len(shared) >= max(2, smaller * 0.6):
                found.append(f"{first} and {second} both export {sorted(shared)}")
    return found


def verb_and_path():
    routes = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"',
                        (APP / "routers" / "api.py").read_text())
    return [f"{v.upper()} {p}" for (v, p), n in Counter(routes).items() if n > 1]


def test_names():
    seen = defaultdict(list)
    for path in sorted(TESTS.glob("test_*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                seen[node.name].append(path.name)
    return [f"{n} in {ps}" for n, ps in sorted(seen.items()) if len(ps) > 1]


def migration_columns():
    bodies = defaultdict(list)
    for node in ast.parse((APP / "migrations.py").read_text()).body:
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("_migrate_v")):
            continue
        columns = tuple(sorted(re.findall(
            r'_add_column\(conn, db\.(\w+), "(\w+)"', ast.unparse(node))))
        if columns:
            bodies[columns].append(node.name)
    return [f"{fns} all add {list(cols)}"
            for cols, fns in bodies.items() if len(fns) > 1]


def class_across_modules():
    where = defaultdict(set)
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                where[node.name].add(path.name)
    return [f"{n} in {sorted(ps)}" for n, ps in sorted(where.items()) if len(ps) > 1]


def shared_constants():
    """A module-level constant table defined in two modules.

    ORIGIN_RANK - the ladder that decides which evidence outranks which - was
    defined in refinement.py and locations.py, identically. Identical is how
    this stays invisible: a second ladder ranks the same evidence in two
    places, and the one that drifts is the one nobody is reading.

    Only upper-case names bound to a dict, set, tuple or list: a scalar
    constant repeated is usually a coincidence, a repeated table is a
    vocabulary.
    """
    where = defaultdict(set)
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not (isinstance(node, ast.Assign)
                    and isinstance(node.value, (ast.Dict, ast.Set, ast.Tuple,
                                                ast.List))):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Name) and target.id.isupper()
                        and len(target.id) > 3):
                    where[target.id].add(path.name)
    return [f"{name} defined in {sorted(paths)}"
            for name, paths in sorted(where.items()) if len(paths) > 1]


def panel_headings():
    where = defaultdict(set)
    for path in sorted(UI.rglob("*.py")):
        for heading in re.findall(r'st\.subheader\("([^"]+)"\)', path.read_text()):
            where[heading].add(path.name)
    return [f"{h!r} on {sorted(ps)}" for h, ps in sorted(where.items()) if len(ps) > 1]


CHECKS = (
    ("the same name twice in one module", same_module_names),
    ("two domain modules exporting the same set", cross_module_exports),
    ("two handlers on one verb and path", verb_and_path),
    ("the same test name in two files", test_names),
    ("two migrations adding one column", migration_columns),
    ("one class defined in two modules", class_across_modules),
    ("one panel heading on two pages", panel_headings),
    ("one constant table in two modules", shared_constants),
)


def main() -> int:
    total = 0
    for name, check in CHECKS:
        found = check()
        total += len(found)
        print(f"[{'FAIL' if found else 'ok  '}]  {name}")
        for item in found:
            print(f"          - {item}")
    print()
    if total:
        print(f"{total} duplication(s). Python keeps the last definition and "
              f"runs, so each is something silently replaced.")
        return 1
    print("No duplication in any of the seven shapes it has taken here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
