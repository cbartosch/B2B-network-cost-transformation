"""A scenario cannot save more than the layers it acts on cost.

A hand-built savings ladder for a real client compounded four scenario
families against a single L0 access baseline and produced a 74% saving where
the layer-scoped answer is 21-29%. Two of the four families act on cost pools
that baseline never contained: SASE and appliance retirement on L2/L4, and the
operating-model levers on OPS - which nothing in this model ever prices.

`scenarios()` was right. It scopes by layer, so those levers booked nothing.
What was missing was any signal that they had booked nothing *because the cost
pool is unmeasured* rather than because the scenario is empty - and any check
that a consumer computing the ladder by hand had got it wrong.

Two levers act on OPS and no OPS cost exists anywhere in the model, so
scenario D's 34 percentage points have nowhere to land. That is the same
defect as the inert industry benchmark and the dead `countries` parameter: a
governed input that reaches no output.
"""
import importlib.machinery
import pathlib
import re
import sys
import types
from decimal import Decimal as D, ROUND_HALF_UP, getcontext

import pytest


def _load():
    """`scenarios` and `Component`, without a database or pydantic."""
    app = pathlib.Path(__file__).resolve().parents[1]
    app = next(c for c in (app / "api_service" / "app", app / "app")
               if (c / "domain").exists())
    for lib in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc", "psycopg"):
        stub = types.ModuleType(lib)
        stub.__getattr__ = lambda _n: type("A", (), {
            "__getattr__": lambda s, _x: s,
            "__call__": lambda s, *a, **k: s})()
        stub.__spec__ = importlib.machinery.ModuleSpec(lib, loader=None)
        sys.modules.setdefault(lib, stub)

    money = {"Decimal": D, "getcontext": getcontext,
             "ROUND_HALF_UP": ROUND_HALF_UP}
    exec("\n".join(l for l in (app / "domain" / "money.py").read_text()
                   .splitlines() if not l.startswith(("from ", "import "))),
         money)
    access = {"re": re, "Decimal": D}
    text = (app / "domain" / "access.py").read_text()
    exec(text[text.index("DIA = "):], access)

    namespace = dict(money)
    namespace.update({
        "access": types.SimpleNamespace(**access), "re": re,
        "dataclass": __import__("dataclasses").dataclass,
        "field": __import__("dataclasses").field,
        "transition": types.SimpleNamespace(net=lambda **k: {}),
        "locations": types.SimpleNamespace(), "SIMULATED": "SIMULATED"})
    source = (app / "domain" / "estimate.py").read_text()
    exec("\n".join(l for l in source[source.index("@dataclass"):].splitlines()
                   if not l.startswith(("from ", "import "))), namespace)
    return namespace


NS = _load()


def _levers():
    from app.seed import LEVERS
    return [{"lever_id": r[0], "family": r[1], "description": r[2],
             "cost_layers": r[3], "saving_low": r[4], "saving_base": r[5],
             "saving_high": r[6], "applies_to_service_classes": r[7],
             "applies_to_access_technologies": r[8],
             "applies_to_platform_products": r[9], "scenario": r[10],
             # Role scope, added when a backbone lever needed to say what a
             # circuit is FOR rather than what it is. Read by index like the
             # rest, and the row is now 13 wide.
             "applies_to_roles": r[12] if len(r) > 12 else None}
            for r in LEVERS]


def _component(layer, base, **extra):
    spec = dict(key=layer, layer=layer, driver="circuits", quantity=1,
                quantity_origin="ANALYST_ENTERED_SCOPE",
                unit_cost_origin="BENCHMARK_PRIOR", product="DIA",
                role="PRIMARY", service_class="DIA", access_technology=None,
                bearer_mbps=None, committed_mbps=None,
                value=NS["Range"](D(base) * D("0.8"), D(base),
                                  D(base) * D("1.3")))
    spec.update(extra)
    return NS["Component"](**spec)


def test_an_unmeasured_cost_layer_is_reported_not_silently_zero():
    """Scenario C acts on L2 and L4. On an access-only estate it booked
    nothing and said nothing, so an empty scenario was indistinguishable from
    a scenario with no opportunity in it."""
    out = NS["scenarios"]([_component("L0", "20104740")], _levers())
    reasons = {n["lever_id"]: n["reason"]
               for n in out["C"]["levers_not_applicable"]}
    assert "LEV-SASE-001" in reasons
    assert "no baseline for" in reasons["LEV-SASE-001"]
    assert "unmeasured" in reasons["LEV-SASE-001"]


def test_the_ops_levers_have_nowhere_to_land():
    """Two levers act on OPS - 34 percentage points of the lever book - and
    nothing in this model ever prices an OPS cost."""
    from app.seed import LEVERS, PLATFORM

    ops_levers = [r[0] for r in LEVERS if "OPS" in r[3]]
    assert len(ops_levers) == 2, ops_levers
    priced_layers = {row[1] for row in PLATFORM} | {"L0"}
    assert "OPS" not in priced_layers, (
        "if OPS is now priced, this test and the reporting can be relaxed")


def test_a_saving_cannot_exceed_its_own_addressable_base():
    """The check that would have caught the 74%."""
    out = NS["scenarios"]([_component("L0", "20104740")], _levers())
    for code, scenario in out.items():
        ceiling = scenario["ceiling"]
        assert ceiling["within_ceiling"], (code, ceiling["note"])
        assert D(ceiling["saving_base"]) <= D(ceiling["addressable_base"]) \
            or D(ceiling["addressable_base"]) == 0


def test_the_ceiling_names_the_layers_it_measured_against():
    """A ceiling without its basis is unactionable."""
    out = NS["scenarios"]([_component("L0", "20104740")], _levers())
    # Scenario C gained LEV-BACKBONE-001 on L0 and LEV-POP-001 on L1, so the
    # layers it addresses are wider than the platform pair it started as.
    # Asserted as a superset: the point is that the ceiling names what it
    # measured against, not that the set never grows.
    assert set(out["C"]["ceiling"]["layers_addressed"]) >= {"L2", "L4"}
    assert out["A"]["ceiling"]["layers_addressed"] == ["L0"]


def test_a_scenario_with_no_priced_layer_reports_zero_addressable():
    """Not an error - an honest zero.

    Scenario C used to be platform-only, so an access-only estate made it
    zero. It now also carries LEV-BACKBONE-001 on L0 and LEV-POP-001 on L1,
    so the estate has to lack every layer the scenario touches for the zero
    to be the point.

    A PRIMARY-only L0 estate is that case: the backbone lever is scoped to
    role=BACKBONE and finds nothing, the PoP lever has no L1, and the two
    platform levers have no L2 or L4."""
    out = NS["scenarios"]([_component("L0", "20104740")], _levers())
    assert D(out["C"]["gross_run_rate_savings"]["base"]) == 0
    # And it says which levers found nothing, rather than reporting a bare
    # zero somebody would read as "no opportunity here".
    assert len(out["C"]["levers_not_applicable"]) == 4


def test_a_fully_layered_estate_books_the_platform_levers():
    """The other half of the proof: given an L2/L4 baseline, scenario C
    stops being empty."""
    # L1 too, since LEV-POP-001 acts on it. The estate has to carry every
    # layer scenario C addresses or the assertion below is testing the
    # estate's gaps rather than the scenario's arithmetic.
    # Every layer AND every role scenario C addresses. LEV-BACKBONE-001 is
    # scoped to role=BACKBONE - a backbone link is Ethernet like every other
    # circuit and differs only in what it is for - so an estate of PRIMARY
    # components alone leaves it inapplicable, correctly.
    out = NS["scenarios"]([
        _component("L0", "20104740"),
        # `_component` takes the layer positionally and passes **extra to the
        # Component, so `layer=` here was the same argument twice. The key is
        # overridden instead, since two components in one layer need distinct
        # keys.
        _component("L0", "1800000", key="L0_backbone", role="BACKBONE",
                   product="ETHERNET", service_class="ETHERNET"),
        _component("L1", "576000", product="POP_COLOCATION",
                   role="PLATFORM"),
        _component("L2", "990000", product="SDWAN_OVERLAY",
                   role="PLATFORM"),
        _component("L4", "1890000", product="SSE_LICENCE",
                   role="PLATFORM"),
    ], _levers())
    assert D(out["C"]["gross_run_rate_savings"]["base"]) > 0
    assert not out["C"]["levers_not_applicable"]


def test_a_lever_is_reported_once_not_twice():
    """A lever failing on both its layer and a product constraint was listed
    under each. The layer is the reason that matters - there is no cost pool
    for the constraint to narrow."""
    out = NS["scenarios"]([_component("L0", "20104740")], _levers())
    for scenario in out.values():
        ids = [n["lever_id"] for n in scenario["levers_not_applicable"]]
        assert len(ids) == len(set(ids)), ids
