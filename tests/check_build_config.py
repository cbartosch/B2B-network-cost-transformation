#!/usr/bin/env python3
"""Pre-build checks. Standard library only, run on the host before `docker build`.

The container test suite cannot validate the build that produces the container:
a broken Dockerfile means the image never builds, so the test that would have
caught it never runs. Both real failures on first launch were this shape - a
duplicate compose key and a COPY of a path that does not exist - and neither was
reachable from inside the image.

No third-party imports, so this runs with any Python: `make check`, or
`python tests/check_build_config.py`.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
problems: list = []


def _build() -> str:
    """Printed on every run. Two launch failures were reported against a stale
    extraction, because PowerShell's Expand-Archive will not overwrite existing
    files without -Force and says nothing when it declines."""
    marker = ROOT / "VERSION"
    if not marker.exists():
        return "unknown (no VERSION file - this is an old extraction)"
    for line in marker.read_text().splitlines():
        if line.startswith("build:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def _duplicate_keys(path: Path) -> list:
    """Duplicate mapping keys within one block.

    PyYAML's default loader keeps the last of a duplicate and reports success;
    Compose's Go parser refuses the file. A small indentation-aware scan catches
    the case that matters without needing a YAML library on the host.
    """
    found, seen = [], {}
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([A-Za-z_][\w.-]*):(\s|$)", raw)
        if not match:
            continue
        indent, key = len(match.group(1)), match.group(2)
        for deeper in [i for i in seen if i > indent]:
            del seen[deeper]                      # leaving a nested block
        block = seen.setdefault(indent, {})
        if key in block:
            found.append(f"{path.name}:{number} duplicate key '{key}' "
                         f"(first at line {block[key]})")
        else:
            block[key] = number
    return found


def _forward_references(path: Path) -> list:
    """Names used in a module-level signature before they are defined.

    Python resolves annotations at definition time, so a route annotated with a
    model declared further down the file raises NameError on import. The API
    container exited on exactly this the first time it ran: five request models
    were introduced anchored to a class near the bottom of the file, landing 570
    lines after the routes using them.

    py_compile does not catch it - the syntax is valid. This does, on the host,
    before a build.
    """
    import ast

    tree = ast.parse(path.read_text())
    declared = {n.name: n.lineno for n in tree.body if isinstance(n, ast.ClassDef)}
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for arg in node.args.args + node.args.kwonlyargs:
            name = getattr(getattr(arg, "annotation", None), "id", None)
            if name in declared and node.lineno < declared[name]:
                found.append(
                    f"{path.name}:{node.lineno} {node.name}() is annotated with "
                    f"{name}, defined later at line {declared[name]} - NameError "
                    f"at import")
    return found


def _undefined_names(path: Path) -> list:
    """Names read but never bound anywhere in the module.

    `py_compile` accepts these - the syntax is valid - so they surface only when
    the line executes. Two shipped: `CANCELLING` and `_now` in jobs.py, which
    together accounted for a third of the first real test run's failures.

    Deliberately conservative: any binding anywhere in the module counts, so
    this reports names that are genuinely absent rather than merely used before
    assignment.
    """
    import ast
    import builtins

    tree = ast.parse(path.read_text())
    bound = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__spec__",
                                  "self", "cls"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.comprehension):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.Global):
            bound.update(node.names)
    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return [f"{path.name}: '{n}' is used but never defined" for n in sorted(used - bound)]


def _copy_sources(dockerfile: Path) -> list:
    return [m.group(1) for m in
            re.finditer(r"^COPY\s+(\S+)\s+(\S+)", dockerfile.read_text(), re.M)]


def main() -> int:
    print(f"network-workbench build {_build()}  ({ROOT})\n")
    compose = ROOT / "docker-compose.yml"
    if compose.exists():
        problems.extend(_duplicate_keys(compose))
    else:
        problems.append("docker-compose.yml not found")

    # Build context is the repository root for both images; a COPY source is
    # resolved against that, not against the Dockerfile's own directory.
    for dockerfile in ("api_service/Dockerfile", "analyst_ui/Dockerfile"):
        path = ROOT / dockerfile
        if not path.exists():
            problems.append(f"{dockerfile} not found")
            continue
        for src in _copy_sources(path):
            if not (ROOT / src).exists():
                problems.append(
                    f"{dockerfile}: COPY {src} - no such path in the build context")

    for source in sorted((ROOT / "api_service" / "app").rglob("*.py")):
        problems.extend(_forward_references(source))
        problems.extend(_undefined_names(source))

    if problems:
        print("Build configuration problems:\n")
        for p in problems:
            print(f"  {p}")
        print("\nFix these before building; the image cannot be built to test them.")
        return 1
    print("Build configuration OK: no duplicate compose keys, all COPY paths "
          "exist, no forward-referenced annotations, no undefined names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
