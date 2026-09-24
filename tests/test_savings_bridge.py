"""Baseline to target, one step per lever, in the order they compound.

Three things the scenario output does not show on its own:

  * ORDER. Levers compound - each acts on what the ones before it left. As a
    flat list they read as additive and a reader adds them up. Repricing a
    circuit and then deleting it is the classic double count and it is
    invisible in a list.
  * BASIS. A governed lever, an analyst's estimate, and a lever that found
    nothing to act on are identical in a total and mean entirely different
    things.
  * WHAT WAS NOT COUNTED. A lever with no cost pool contributes nothing, and
    a bridge that omits it presents a smaller opportunity as a complete one.
"""
from decimal import Decimal

from app.domain import savings_bridge as bridge


SCENARIOS = {
    "A": {"levers": [
        {"lever_id": "LEV-REPRICE-001", "family": "Same-service repricing",
         "saving_base": "2416000", "cost_layers": ["L0"]}],
        "levers_not_applicable": []},
    "B": {"levers": [],
          "levers_not_applicable": [
              {"lever_id": "LEV-MPLS-001", "family": "MPLS substitution",
               "reason": "acts on service_class in ['IPVPN'], and this "
                         "estate's service classes are DIA, ETHERNET"}]},
    "C": {"levers": [],
          "levers_not_applicable": [
              {"lever_id": "LEV-SASE-001", "family": "Platform consolidation",
               "reason": "acts on L2/L4, and this estimate has no baseline "
                         "for L2/L4"}]},
}


def _built():
    return bridge.waterfall(SCENARIOS, current_total="20000000",
                            extra_steps=[{
                                "step": "Backbone to hyperscaler",
                                "saving": "1570000",
                                "because": "no PoP baseline in the model"}])


def test_the_steps_compound_rather_than_adding():
    """Each step starts where the last one ended."""
    built = _built()
    for step in built["steps"]:
        assert Decimal(step["to"]) == Decimal(step["from"]) - Decimal(
            step["saving"])
    chain = built["steps"]
    for earlier, later in zip(chain, chain[1:]):
        assert later["from"] == earlier["to"]


def test_it_reconciles():
    """A bridge that nearly reconciles has lost something, and the thing it
    lost is what somebody will ask about."""
    assert bridge.reconciles(_built())


def test_a_governed_lever_and_an_estimate_are_distinguishable():
    built = _built()
    bases = {s["basis"] for s in built["steps"]}
    assert bridge.GOVERNED in bases
    assert bridge.ESTIMATE in bases
    assert built["governed_saving"] != built["total_saving"], (
        "an estimate must not be folded into the governed total")


def test_a_lever_with_no_baseline_is_a_hole_not_a_zero():
    """"No cost pool to act on" and "worth nothing" are different findings,
    and only the first is a gap in the model."""
    built = _built()
    kinds = {k["basis"] for k in built["not_counted"]}
    assert bridge.NO_BASELINE in kinds
    assert bridge.NOT_APPLICABLE in kinds


def test_what_was_not_counted_never_enters_the_total():
    built = _built()
    counted = sum(Decimal(s["saving"]) for s in built["steps"])
    assert Decimal(built["total_saving"]) == counted
    assert built["not_counted"], "the sample has two"


def test_the_governed_share_is_reported():
    """A bridge that is mostly estimate is a hypothesis with a chart."""
    built = _built()
    assert Decimal(built["governed_share"]) < 1
    assert Decimal(built["governed_share"]) > 0


def test_the_note_names_the_levers_that_found_nothing():
    note = _built()["note"]
    assert "compound" in note
    assert "Platform consolidation" in note
    assert "not one worth zero" in note


def test_the_bridge_reaches_the_estimate_response():
    """A module nothing imports is the defect validate_flow caught on the
    first run of this one."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert api.count('"savings_bridge": savings_bridge.waterfall(') == 2, (
        "both the run and the read response must carry it")
