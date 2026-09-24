"""Two levers must not remove the same cost twice.

`remaining[key]` decrements per lever, so two levers acting on one component
compound: repricing took 12% and MPLS substitution then took 25% of the
remaining 88%. For that pair the arithmetic is wrong - you either renegotiate
a circuit or you replace it, and if you replace it the repricing saving never
materialises.

The harder half is across scenarios. `scenarios()` computes each scenario
independently from the full baseline - A is 14.6% of the whole and B is 25% of
the whole - and resolves exclusivity only WITHIN a scenario, because that is
all it can see. Repricing sits in A and MPLS substitution in B, so the two
never meet there. The waterfall is the only place that sees all four at once.
"""
from decimal import Decimal as D
from pathlib import Path

from app.domain import savings_bridge as bridge


def test_the_lever_rows_declare_their_exclusions():
    from app.seed import LEVERS

    excludes = {r[0]: r[13] for r in LEVERS}
    assert excludes["LEV-REPRICE-001"], "repricing must exclude replacement"
    assert "LEV-MPLS-001" in excludes["LEV-REPRICE-001"]
    assert "LEV-REPRICE-001" in excludes["LEV-MPLS-001"], (
        "exclusivity has to be declared both ways or the order decides it")


def test_an_exclusion_is_symmetric():
    """A one-way exclusion means whichever lever happens to run first wins,
    which makes the arithmetic depend on sort order."""
    from app.seed import LEVERS

    excludes = {r[0]: set(r[13] or []) for r in LEVERS}
    for lever_id, peers in excludes.items():
        for peer in peers:
            assert lever_id in excludes.get(peer, set()), (
                f"{lever_id} excludes {peer} and {peer} does not exclude "
                f"{lever_id}")


def test_the_larger_saving_is_the_one_booked():
    """Exclusivity is resolved by which lever runs first, so the order has to
    put the better one there. Sorting by lever_id made the winner
    alphabetical."""
    scenarios = {
        "A": {"levers": [{"lever_id": "LEV-MPLS-001",
                          "family": "MPLS substitution",
                          "saving_base": "2500000",
                          "excludes": ["LEV-REPRICE-001"]}],
              "levers_not_applicable": []},
        "B": {"levers": [{"lever_id": "LEV-REPRICE-001",
                          "family": "Same-service repricing",
                          "saving_base": "1200000",
                          "excludes": ["LEV-MPLS-001"]}],
              "levers_not_applicable": []},
    }
    built = bridge.waterfall(scenarios, current_total="10000000")
    booked = [s["lever_id"] for s in built["steps"]]
    assert booked == ["LEV-MPLS-001"]
    assert D(built["total_saving"]) == D("2500000"), (
        "both booked would be 3,700,000 - the double count this exists for")


def test_the_excluded_lever_is_reported_not_dropped():
    """A lever not taken BECAUSE a better one was is a different finding from
    one that found nothing. The opportunity was counted once, not missed."""
    scenarios = {
        "A": {"levers": [{"lever_id": "LEV-MPLS-001", "family": "MPLS",
                          "saving_base": "2500000",
                          "excludes": ["LEV-REPRICE-001"]}],
              "levers_not_applicable": []},
        "B": {"levers": [{"lever_id": "LEV-REPRICE-001", "family": "Repricing",
                          "saving_base": "1200000",
                          "excludes": ["LEV-MPLS-001"]}],
              "levers_not_applicable": []},
    }
    built = bridge.waterfall(scenarios, current_total="10000000")
    excluded = [k for k in built["not_counted"]
                if k["basis"] == bridge.EXCLUDED]
    assert excluded
    assert "already booked" in excluded[0]["reason"]
    assert "Counted once, not missed" in built["note"]


def test_it_still_reconciles():
    scenarios = {
        "A": {"levers": [{"lever_id": "LEV-MPLS-001", "family": "MPLS",
                          "saving_base": "2500000",
                          "excludes": ["LEV-REPRICE-001"]}],
              "levers_not_applicable": []},
        "B": {"levers": [{"lever_id": "LEV-REPRICE-001", "family": "Repricing",
                          "saving_base": "1200000",
                          "excludes": ["LEV-MPLS-001"]}],
              "levers_not_applicable": []},
    }
    assert bridge.reconciles(
        bridge.waterfall(scenarios, current_total="10000000"))


def test_scenarios_resolves_exclusivity_within_itself_too():
    """Both halves are needed: within a scenario `scenarios()` catches it per
    component, and across scenarios only the waterfall can."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "estimate.py").read_text()
    assert "cut_by.get(" in source
    assert "cut_by.setdefault(" in source


def test_an_exclusion_reason_is_not_spliced_into_a_constraint_message():
    """The not-applied template assumed every skip was a constraint
    mismatch, so an exclusion arrived as "acts on service_class in [...], and
    this estate's excluded by LEV-MPLS-001 on this component in L0 contain
    none of them"."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "estimate.py").read_text()
    assert "is excluded on every component it" in source
    assert 'x.startswith("excluded by")' in source
