"""Why the estimate moved, reconciled to the last penny.

Specification 0.5D and 12.3. `estimate_snapshot.supersedes_snapshot_id` already
carried the lineage, so the system could say *that* an estimate changed and not
why - and "the baseline moved 12%" is not an answer anyone accepts.
"""
import pytest

from app.domain import delta_bridge


def _attrs():
    return [
        {"driver": delta_bridge.VOLUME, "value": "-400000",
         "because": "340 sites, not 440"},
        {"driver": delta_bridge.UNIT_PRICE, "value": "-150000",
         "because": "GB benchmark landed"},
        {"driver": delta_bridge.FX, "value": "80000",
         "because": "GBP/USD moved"},
    ]


def test_a_bridge_that_accounts_for_everything_reconciles():
    out = delta_bridge.bridge(from_total="4600000", to_total="4130000",
                              attributions=_attrs())
    assert out["residual"] == "0"
    assert out["reconciles"] is True


def test_a_residual_is_reported_never_distributed():
    """A bridge that nearly reconciles has lost something, and the thing it
    lost is the part somebody will ask about. Folding it into the nearest
    driver makes the arithmetic tidy and the explanation false."""
    out = delta_bridge.bridge(from_total="4600000", to_total="4000000",
                              attributions=_attrs())
    assert out["reconciles"] is False
    assert out["residual"] == "-130000"
    # and no driver absorbed it
    assert sum(int(d["value"]) for d in out["drivers"]) == -470000


def test_all_eight_drivers_are_present_even_at_zero():
    """A bridge is read as a waterfall, and a category silently absent is
    indistinguishable from one that did not move."""
    out = delta_bridge.bridge(from_total="1", to_total="1", attributions=[])
    assert [d["driver"] for d in out["drivers"]] == list(delta_bridge.DRIVERS)
    assert len(out["drivers"]) == 8


def test_a_ninth_category_is_refused():
    """A ninth invented at write time is how FX ends up inside baseline
    cost."""
    with pytest.raises(delta_bridge.BridgeIncomplete, match="not delta drivers"):
        delta_bridge.bridge(from_total="0", to_total="0",
                            attributions=[{"driver": "misc", "value": "1"}])


def test_fx_and_scope_are_their_own_drivers():
    """The spec is explicit: "FX never hides inside baseline cost", and a scope
    change is "never absorbed into another driver". A country leaving the
    estate and a country getting cheaper look identical in a total and are
    entirely different findings."""
    assert delta_bridge.FX in delta_bridge.DRIVERS
    assert delta_bridge.SCOPE in delta_bridge.DRIVERS
    out = delta_bridge.bridge(
        from_total="100", to_total="90",
        attributions=[{"driver": delta_bridge.FX, "value": "-10"}])
    fx = next(d for d in out["drivers"] if d["driver"] == delta_bridge.FX)
    baseline = next(d for d in out["drivers"]
                    if d["driver"] == delta_bridge.BASELINE_COST)
    assert fx["value"] == "-10" and baseline["value"] == "0"


def test_policy_movement_is_reported_before_the_residual_test():
    """A total that moved because the calculation version changed is not a
    finding about the client, and attributing it to a driver would describe the
    wrong thing entirely."""
    out = delta_bridge.bridge(
        from_total="100", to_total="100", attributions=[],
        from_pins={"calculation_version": "calc-1.0.0"},
        to_pins={"calculation_version": "calc-1.1.0"})
    assert out["policy"]["comparable"] is False
    assert "calculation_version" in out["policy"]["moved"]


def test_identical_pins_compare_cleanly():
    out = delta_bridge.bridge(
        from_total="100", to_total="100", attributions=[],
        from_pins={"calculation_version": "calc-1.1.0"},
        to_pins={"calculation_version": "calc-1.1.0"})
    assert out["policy"]["comparable"] is True
    assert "about the estate rather than about the model" in out["policy"]["note"]


def test_an_unmapped_lever_and_a_doubly_mapped_one_are_different_faults():
    """An unmapped lever's saving lands nowhere and shows up as residual. A
    doubly-mapped one lands twice and makes the bridge reconcile while
    double-counting - which is the worse fault because it looks correct."""
    out = delta_bridge.check_lever_mapping(
        [{"lever_id": "A"}, {"lever_id": "B"}, {"lever_id": "C"}],
        {"A": [delta_bridge.UNIT_PRICE],
         "B": [delta_bridge.UNIT_PRICE, delta_bridge.VOLUME]})
    assert out["unmapped"] == ["C"]
    assert out["mapped_more_than_once"][0]["lever_id"] == "B"
    assert out["passes"] is False


def test_every_driver_declares_its_earliest_stage():
    """§0.5D's evidence rule. Reported rather than enforced - a baseline moving
    at V1 without commercial evidence is a finding about the estimate."""
    for driver in delta_bridge.DRIVERS:
        assert driver in delta_bridge.EARLIEST_STAGE
    assert delta_bridge.EARLIEST_STAGE[delta_bridge.EXECUTION] == "V5"


def test_the_bridge_is_additive_and_changes_no_existing_calculation():
    """Nothing existing writes or reads estimate_delta, and a snapshot without
    a bridge behaves exactly as before."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "db.py").exists())
    users = []
    for path in (app / "domain").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute)
                    and node.attr == "estimate_delta"
                    and getattr(node.value, "id", "") == "db"):
                users.append(path.name)
    assert not users, (
        f"{users} read estimate_delta - the bridge explains the estimate and "
        f"must not feed it")
