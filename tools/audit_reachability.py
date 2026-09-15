#!/usr/bin/env python3
"""What in here is not reachable from anything?

The dominant defect class in this repository. A partial list from one session:
the access vocabulary nobody imported, `fx_convention` collected and never
read, `expires` written on every prior and ignored, `unsourced_price_share`
computed and on no screen, two endpoint pairs no page called, `run_ensemble`
accepting a parameter and dropping it, a benchmark table not re-keyed so the
evidence path could not reach the rate card, 31 static guards in files that ran
nowhere, and five class constants trimmed out of a policy.

Every one was found late. This looks for the rest, by AST rather than by
substring - a proximity match in a concatenated blob reports almost everything
as fine, which is the failure mode of the first three versions of this idea.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
UI = ROOT / "analyst_ui"
TESTS = ROOT / "tests"
TOOLS = ROOT / "tools"


def _py(root):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))


def _tree(path):
    try:
        return ast.parse(path.read_text())
    except SyntaxError:
        return None


APP_FILES = _py(APP)
UI_TEXT = "\n".join(p.read_text() for p in _py(UI))
TEST_TEXT = "\n".join(p.read_text() for p in _py(TESTS))
TOOL_TEXT = "\n".join(p.read_text() for p in _py(TOOLS))


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


# ------------------------------------------------------------- 1. modules
section("1. domain modules nothing imports")
modules = {p.stem for p in (APP / "domain").glob("*.py")} - {"__init__"}
importers = {m: set() for m in modules}
for path in APP_FILES:
    tree = _tree(path)
    if tree is None:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = (node.module or "").split(".")[-1]
        if node.module is None or base == "domain":
            for alias in node.names:
                if alias.name in modules and path.stem != alias.name:
                    importers[alias.name].add(path.stem)
        elif base in modules and path.stem != base:
            importers[base].add(path.stem)
orphans = sorted(m for m, v in importers.items() if not v)
tool_only = sorted(m for m, v in importers.items()
                   if v and m in TOOL_TEXT and not (v - {"__init__"}))
print(f"  {len(modules)} modules, {len(orphans)} imported by nothing")
for m in orphans:
    print(f"    {m}" + ("   (a tool imports it)" if m in TOOL_TEXT else ""))

# ----------------------------------------------------------- 2. functions
section("2. public functions nothing calls")
called = set()
for path in APP_FILES + _py(TESTS) + _py(TOOLS):
    tree = _tree(path)
    if tree is None:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called.add(getattr(node.func, "attr", None)
                       or getattr(node.func, "id", None))
        # inspect.getsource(x) and getattr(m, "x") are uses too
        if isinstance(node, ast.Attribute):
            called.add(node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            called.add(node.value)
uncalled = []
for path in APP_FILES:
    tree = _tree(path)
    if tree is None:
        continue
    for node in tree.body:
        if (isinstance(node, ast.FunctionDef)
                and not node.name.startswith("_")
                and node.name not in called
                and not any("router" in ast.unparse(d)
                            for d in node.decorator_list)):
            uncalled.append(f"{path.relative_to(APP)}::{node.name}")
print(f"  {len(uncalled)} uncalled:")
for u in uncalled:
    print(f"    {u}")

# -------------------------------------------------------------- 3. routes
section("3. routes")
api = (APP / "routers" / "api.py").read_text()
routes = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"', api)


def _reached(path, corpus):
    if path in corpus:
        return True
    segments = [s for s in re.sub(r"\{[^}]+\}", "", path).split("/") if s]
    if not segments:
        return False
    tail = segments[-1].split(":")[-1]
    return bool(tail) and tail in corpus


no_screen = [f"{v.upper():6} {p}" for v, p in routes if not _reached(p, UI_TEXT)]
no_test = [f"{v.upper():6} {p}" for v, p in routes if not _reached(p, TEST_TEXT)]
print(f"  {len(routes)} routes")
print(f"  {len(no_screen)} reached by no screen")
for r in no_screen:
    print(f"    {r}")
print(f"  {len(no_test)} named by no test")

# -------------------------------------------------------------- 4. tables
section("4. tables")
db_source = (APP / "db.py").read_text()
tables = re.findall(r"^(\w+) = Table\(", db_source, re.M)
app_text = "\n".join(p.read_text() for p in APP_FILES if p.name != "db.py")
for table in sorted(tables):
    written = bool(re.search(rf"insert\(db\.{table}\)|update\(db\.{table}\)",
                             app_text))
    read = bool(re.search(rf"select\(db\.{table}[.)]", app_text))
    if not read and not written:
        print(f"    {table}: neither read nor written anywhere")
    elif not read:
        print(f"    {table}: written, never read")
    elif not written:
        print(f"    {table}: read, never written (seed-only or governed)")

# ------------------------------------------------------------- 5. columns
section("5. columns nothing names")
unused = []
for match in re.finditer(r"^(\w+) = Table\(", db_source, re.M):
    table, start = match.group(1), match.start()
    end = db_source.index("schema=", start)
    for column in re.findall(r'Column\("(\w+)"', db_source[start:end]):
        if column in ("id",):
            continue
        named = (re.search(rf"\b{column}\b", app_text)
                 or column in UI_TEXT or column in TEST_TEXT)
        if not named:
            unused.append(f"{table}.{column}")
print(f"  {len(unused)} columns named nowhere outside db.py:")
for u in unused:
    print(f"    {u}")

# ---------------------------------------------------------- 6. thresholds
section("6. governed thresholds nothing consumes")
seed_source = (APP / "seed.py").read_text()
start = seed_source.index("THRESHOLDS = [")
namespace = {}
exec(seed_source[start:seed_source.index("\n]\n", start) + 3], namespace)
policy_source = (APP / "domain" / "policy.py").read_text()
unconsumed = []
for row in namespace["THRESHOLDS"]:
    key = row[1]
    if key in policy_source or key in app_text:
        continue
    # band_1_floor style keys are read by an index loop
    if re.match(r".*_\d+_(floor|label|upper|ceiling)$", key):
        continue
    unconsumed.append(f"{row[0]}.{key}")
print(f"  {len(namespace['THRESHOLDS'])} seeded, {len(unconsumed)} consumed by "
      f"nothing:")
for u in unconsumed:
    print(f"    {u}")

# ------------------------------------------- 7. computed fields on no screen
section("7. computed output fields that reach no screen")
interesting = set()
for path in _py(APP / "domain"):
    tree = _tree(path)
    if tree is None:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if (isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and re.match(r"^[a-z][a-z0-9_]{6,}$", key.value)):
                interesting.add(key.value)
never_shown = sorted(f for f in interesting
                     if f not in UI_TEXT and f not in TEST_TEXT)
print(f"  {len(interesting)} distinct output keys, {len(never_shown)} in no "
      f"screen and no test:")
for f in never_shown[:24]:
    print(f"    {f}")
if len(never_shown) > 24:
    print(f"    ... and {len(never_shown) - 24} more")

# -------------------------------------------------------------- 8. pages
section("8. interface pages nothing links")
pages = sorted(p.name for p in (UI / "streamlit_app" / "pages").glob("*.py"))
print(f"  {len(pages)} pages (Streamlit auto-routes these, so none can be "
      f"orphaned)")

print("\nThis reports reachability, not correctness. A module nothing imports "
      "is certainly unreachable;\na field on no screen may be deliberate. "
      "Each needs a judgement, and this is the list to judge.")
