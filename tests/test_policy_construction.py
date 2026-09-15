"""Every governed policy can actually be built from its rows.

A live failure: "TypeError: FootprintPolicy() takes no arguments" on page 5,
so no footprint could be resolved at all.

`FootprintPolicy` lost its `@dataclass` in 4.165.0 - TransitionPolicy was
inserted immediately above it and the insertion consumed the decorator line. A
plain class has no `__init__` taking keywords, so `from_rows` raised as soon as
it was called.

It survived 28 releases because the class *imports* fine. Nothing in the suite
constructed one, and the 4.173 field-ordering check inspected only classes that
had the decorator - so a class missing one was never examined. This file exists
so that every policy is constructed at least once.
"""
import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from app.domain import policy


def _policy_classes():
    return sorted(
        (name, obj) for name, obj in vars(policy).items()
        if inspect.isclass(obj) and name.endswith("Policy")
        and obj.__module__ == policy.__name__)


def test_there_are_policies_to_check():
    """A test that finds nothing passes for the wrong reason."""
    assert len(_policy_classes()) >= 12


@pytest.mark.parametrize("name", [n for n, _ in _policy_classes()])
def test_every_policy_is_a_dataclass(name):
    """`from_rows` constructs with keywords. A plain class has no __init__ that
    accepts them, and the failure surfaces only when a route calls it."""
    cls = getattr(policy, name)
    assert dataclasses.is_dataclass(cls), (
        f"{name} is not a dataclass, so cls(field=...) in from_rows raises "
        f"TypeError - and the class imports fine, so nothing catches it until "
        f"a route runs")


@pytest.mark.parametrize("name", [n for n, _ in _policy_classes()])
def test_every_policy_is_frozen(name):
    """A governed set a caller could mutate after loading is not governed."""
    cls = getattr(policy, name)
    assert cls.__dataclass_params__.frozen, f"{name} is mutable"


@pytest.mark.parametrize("name", [n for n, _ in _policy_classes()])
def test_every_policy_declares_its_fields_defaults_last(name):
    """A defaulted field before a non-defaulted one is a TypeError at class
    definition - which is how domain/policy.py became unimportable for eleven
    releases in 4.161."""
    fields = dataclasses.fields(getattr(policy, name))
    seen_default = None
    for field in fields:
        has_default = (field.default is not dataclasses.MISSING
                       or field.default_factory is not dataclasses.MISSING)
        if has_default:
            seen_default = field.name
        else:
            assert seen_default is None, (
                f"{name}.{field.name} has no default and follows "
                f"{seen_default} which does")


def test_the_footprint_policy_builds_from_its_governed_rows():
    """The exact call that failed. Page 5 could not resolve a footprint, and
    the error reached the analyst as an Internal Server Error."""
    built = policy.FootprintPolicy.from_rows({
        "max_sites_per_archetype_row": "100",
        "max_sites_per_cluster_row": "2000"})
    assert built.max_sites_per_archetype_row == 100
    assert built.max_sites_per_cluster_row == 2000
    assert built.set_name == "footprint_policy"


def test_an_incomplete_governed_set_is_still_refused():
    """The fix must not make a missing threshold silently acceptable."""
    with pytest.raises(policy.PolicyIncomplete, match="missing"):
        policy.FootprintPolicy.from_rows({})


def test_no_class_calls_cls_with_keywords_without_a_generated_init():
    """The guard for the class, across the whole application rather than just
    policy.py."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    offenders = []
    for path in sorted(app.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            if any("dataclass" in ast.unparse(d) for d in node.decorator_list):
                continue
            constructs = any(
                isinstance(inner, ast.Call)
                and getattr(inner.func, "id", "") == "cls" and inner.keywords
                for inner in ast.walk(node))
            has_init = any(isinstance(item, ast.FunctionDef)
                           and item.name == "__init__" for item in node.body)
            declares = any(isinstance(item, ast.AnnAssign)
                           for item in node.body)
            if constructs and declares and not has_init:
                offenders.append(f"{path.name}::{node.name}")
    assert not offenders, offenders


# ------------------------- a seeded value has to fit the column it goes into
def _thresholds():
    """The THRESHOLDS list, read from the seed's source.

    app.seed imports sqlalchemy, so importing it blocks this wherever there is
    no database - which is exactly where a seed defect needs catching.
    """
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "seed.py").exists())
    source = (app / "seed.py").read_text()
    start = source.index("THRESHOLDS = [")
    namespace = {}
    exec(source[start:source.index("\n]\n", start) + 3], namespace)
    return namespace["THRESHOLDS"]


def test_every_threshold_value_is_a_number():
    """`transition_policy.evidence_grade = "E"` went into
    reference.threshold.value, which is Numeric(12,4). One row out of
    eighty-four, and it took the other eighty-three with it: the seed aborts on
    the insert, so a database gets no thresholds at all and every policy read
    then reports an incomplete governed set.

    A threshold is a number you compare against. An evidence grade is a
    label."""
    from decimal import Decimal, InvalidOperation

    offenders = []
    for row in _thresholds():
        try:
            Decimal(str(row[2]))
        except (InvalidOperation, TypeError, ValueError):
            offenders.append(f"{row[0]}.{row[1]} = {row[2]!r}")
    assert not offenders, offenders


def test_the_transition_grade_is_not_seeded_as_a_threshold():
    """And does not need to be: from_rows reads it with .get(..., "E") rather
    than _require, unlike the five numeric fields beside it."""
    keys = {(row[0], row[1]) for row in _thresholds()}
    assert ("transition_policy", "evidence_grade") not in keys


def test_the_transition_policy_still_carries_a_grade_without_the_row():
    """Removing the row must not lose the grade - the note in transition.py
    reports it, and a payback with no stated evidence quality reads as better
    than it is."""
    built = policy.TransitionPolicy.from_rows({
        "one_time_cost_per_site_low": "400",
        "one_time_cost_per_site_base": "900",
        "one_time_cost_per_site_high": "1800",
        "dual_running_months": "3",
        "sites_migrated_per_month": "120"})
    assert built.evidence_grade == "E"


def test_a_missing_numeric_threshold_is_still_refused():
    """The five that are required must stay required."""
    with pytest.raises(policy.PolicyIncomplete, match="missing"):
        policy.TransitionPolicy.from_rows({"dual_running_months": "3"})
