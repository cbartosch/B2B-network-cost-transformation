"""Some site types may only ever be entered, never derived from a share.

Simmons Bank registered 233 BRANCHES. The branch-network shape gave ATMs 66%
of the estate, so the proposal came back as 60 branches and 153 cash machines.

Two errors in one. A registered count is evidence and a share is a guess, so a
guess must never reinterpret what was counted. And most cash machines sit
INSIDE a branch - they are equipment in a site already counted, not sites.
Only an off-premise unit is a site of its own, and that number depends on the
bank's off-premise strategy rather than on how many branches it has. No ratio
recovers it.
"""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.domain import absolute_counts


def test_a_cash_machine_is_never_proposed():
    assert not absolute_counts.may_be_proposed("ATM")
    assert "ATM" in absolute_counts.ADDITIVE_ONLY


def test_the_types_that_can_be_proposed_still_are():
    for archetype in ("BRANCH", "STORE", "WAREHOUSE", "DC", "LARGE_OFFICE",
                      "SERVICE_POINT", "SELF_SERVICE_TERMINAL", "PLANT"):
        assert absolute_counts.may_be_proposed(archetype), archetype


def test_no_estate_shape_allocates_an_additive_only_type():
    """A shape naming one is the defect. It reinterprets a registered count
    as something the analyst did not count."""
    from app.domain import industries

    offenders = []
    for shape, rows in industries.SHAPES.items():
        for archetype, _band, _share in rows:
            if not absolute_counts.may_be_proposed(archetype):
                offenders.append(f"{shape}/{archetype}")
    assert not offenders, offenders


def test_a_registered_branch_count_stays_branches():
    """233 registered branches must not come back as 60."""
    from app.seed import DENSITY_MIX

    mix = defaultdict(Decimal)
    for industry, archetype, _band, share in DENSITY_MIX:
        if industry == "RETAIL_BANKING":
            mix[archetype] += Decimal(share)
    assert mix["ATM"] == 0, "the shape must not allocate cash machines"
    assert mix["BRANCH"] > Decimal("0.85"), dict(mix)


def test_the_proposer_drops_them_and_renormalises():
    """Dropping a share without renormalising would leave the split short of
    the register, which reads as arithmetic."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "footprint.py").read_text()
    assert "absolute_counts.may_be_proposed(r.archetype)" in source
    assert "_kept = sum(Decimal(str(r.share)) for r in chosen)" in source


def test_the_reason_is_explained_rather_than_the_type_silently_missing():
    """An analyst who expected cash machines needs telling why there are
    none, and what to do instead."""
    note = absolute_counts.additive_note("ATM")
    assert "inside a branch" in note
    assert "locator" in note or "research" in note


def test_every_shape_still_sums_to_one():
    from app.domain import industries

    for shape, rows in industries.SHAPES.items():
        total = sum(Decimal(share) for _a, _b, share in rows)
        assert total == Decimal("1.0000"), (shape, str(total))
