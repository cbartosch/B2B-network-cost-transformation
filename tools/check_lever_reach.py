#!/usr/bin/env python3
"""Does every governed lever move a number on some real estate?

A lever with no cost pool to act on contributes nothing, and contributing
nothing looks exactly like working. This repository shipped three features in
that state: the industry benchmark applied to archetypes no estate contained,
two OPS levers acting on a layer nothing built, and an archetype resolver
silently discarding every pair it was given. All three were seeded, displayed,
audited and inert.

`scenarios()` already reports `levers_not_applicable` with a reason, which is
the control that makes this visible per run. This is the same question asked
once across every estate shape the model can build: a lever that finds nothing
to act on ANYWHERE is not scoped narrowly, it is dead.

Run it before adding a lever and after. A new lever that fails this on the day
it is written is the cheapest possible time to find out.
"""
import importlib.machinery
import pathlib
import sys
import types
from collections import defaultdict
from decimal import Decimal as D

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _stub_attr(name):
    """Answer any attribute with a self-returning placeholder - except the
    dunders.

    A module-level __getattr__ that answers everything also answers
    __path__, and the import machinery then takes the stub for a package and
    tries to iterate what it got back: "TypeError: 'A' object is not
    iterable", raised from importlib with nothing in the message naming the
    stub or the module that wanted it. Raising AttributeError for dunders
    leaves the machinery to report an honest ModuleNotFoundError for the
    submodule that is genuinely missing from the list below.
    """
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    return type("A", (), {"__getattr__": lambda s, _x: s,
                          "__call__": lambda s, *a, **k: s})()


# sqlalchemy.pool is in the list because db.make_engine imports StaticPool
# from it. It was missing, so `from sqlalchemy.pool import StaticPool` asked
# the sqlalchemy stub for __path__, got an "A" back, and the tool died on
# "TypeError: 'A' object is not iterable" from inside importlib - a message
# that names neither the stub nor the import that wanted it.
for _lib in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc", "sqlalchemy.pool",
             "sqlalchemy.engine", "sqlalchemy.dialects",
             "sqlalchemy.dialects.postgresql", "psycopg"):
    _stub = types.ModuleType(_lib)
    _stub.__getattr__ = lambda _n: _stub_attr(_n)
    _stub.__spec__ = importlib.machinery.ModuleSpec(_lib, loader=None)
    sys.modules.setdefault(_lib, _stub)
sys.path[:0] = [str(ROOT), str(ROOT / "api_service")]

from app import seed                                    # noqa: E402
from app.domain import bics                             # noqa: E402


def _layers_an_estate_builds():
    """Which cost layers a priced estate actually produces a component for.

    Read from `build_components` rather than from the LAYERS tuple: the tuple
    declares six and the function emits four, and the gap is exactly where
    the inert levers lived.
    """
    import ast

    source = (ROOT / "api_service" / "app" / "domain" / "estimate.py").read_text()
    tree = ast.parse(source)
    built = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name == "build_components"):
            continue
        for keyword in ast.walk(node):
            if (isinstance(keyword, ast.keyword) and keyword.arg == "layer"
                    and isinstance(keyword.value, ast.Constant)):
                built.add(keyword.value.value)
    return built


def _service_classes_by_shape():
    """The service classes each estate shape can produce.

    A lever scoped to IPVPN is not dead because one estate has none - it is
    dead if NO estate does.
    """
    from app.domain import access

    by_shape = defaultdict(set)
    priors = {row[0]: row for row in seed.ARCHETYPES}
    mix = defaultdict(set)
    for industry, archetype, _band, _share in seed.DENSITY_MIX:
        mix[industry].add(archetype)
    for industry, archetypes in mix.items():
        shape = (bics.shape_for(industry)
                 if industry in bics.SHAPE_OF_BICS else "other")
        for archetype in archetypes:
            row = priors.get(archetype)
            if not row:
                continue
            for product in (row[4], row[5]):
                cls = access.LEGACY_PRODUCT.get(product, (None, None))[0]
                if cls:
                    by_shape[shape].add(cls)
    # A backbone link is Ethernet transport, present in every estate with a
    # data centre in more than one region.
    for shape in by_shape:
        by_shape[shape].add(access.ETHERNET)
    # The "other" bucket holds industries outside the BICS shape map, so it
    # is not an estate shape. Counting it made this report 10 shapes against
    # the 9 the model has, and the documentation was right.
    by_shape.pop("other", None)
    return by_shape


def main() -> int:
    built_layers = _layers_an_estate_builds()
    classes_by_shape = _service_classes_by_shape()
    every_class = set().union(*classes_by_shape.values()) \
        if classes_by_shape else set()

    print(f"LEVER REACH - {len(seed.LEVERS)} levers against "
          f"{len(classes_by_shape)} estate shapes")
    print(f"  layers a priced estate builds: {sorted(built_layers)}")
    print(f"  service classes any estate produces: {sorted(every_class)}")
    print()

    dead, narrow = [], []
    for row in seed.LEVERS:
        lever_id, family = row[0], row[1]
        layers = set(row[3] or [])
        classes = set(row[7] or [])
        reachable_layers = layers & built_layers
        if not reachable_layers:
            dead.append(
                (lever_id, family,
                 f"acts on {sorted(layers)} and a priced estate builds "
                 f"none of those"))
            continue
        if classes and not (classes & every_class):
            dead.append(
                (lever_id, family,
                 f"acts on service classes {sorted(classes)} and no estate "
                 f"shape produces any of them"))
            continue
        if classes:
            shapes_hit = [s for s, c in classes_by_shape.items()
                          if classes & c]
            if len(shapes_hit) < len(classes_by_shape) / 3:
                narrow.append(
                    (lever_id, family,
                     f"reaches {len(shapes_hit)} of "
                     f"{len(classes_by_shape)} shapes"))

    for lever_id, family, why in dead:
        print(f"  [DEAD]   {lever_id:22} {family}")
        print(f"           {why}")
    for lever_id, family, why in narrow:
        print(f"  [NARROW] {lever_id:22} {family}")
        print(f"           {why}")
    if not dead and not narrow:
        print("  every lever reaches a layer a priced estate builds, and a "
              "service class some estate produces.")
    print()
    print(f"{len(dead)} dead, {len(narrow)} narrow")
    # Narrow is a judgement, not a defect: MPLS substitution should be narrow
    # once most estates have left MPLS. Dead is a defect.
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
