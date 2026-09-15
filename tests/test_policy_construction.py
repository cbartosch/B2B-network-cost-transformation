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
