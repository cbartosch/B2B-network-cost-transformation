"""An acknowledged pre-flight report cannot describe a case that has changed.

`assert_clear_to_run` trusted the latest acknowledged report and nothing else.
So a named person could sign off on findings, the case data could change
underneath them, and every later gate still cited that approval - the record of
a human decision describing a case that no longer existed.

The whole design rests on a person taking responsibility at each gate. This is
the check that makes that record mean something.
"""
import types

import pytest

# Loaded from source rather than imported. `app.domain.preflight` imports the
# LLM gateway, which imports pydantic - so importing it blocks this file
# wherever there is no pydantic, which is exactly where a digest defect needs
# catching. The third time this session a guard has been written into a file
# that could not run.
from pathlib import Path as _Path


def _preflight_module():
    import hashlib
    import json

    root = _Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "preflight.py").read_text()
    start = source.index("INPUT_FIELDS = (")
    end = source.index("def run(session")
    namespace = {"hashlib": hashlib, "json": json,
                 "select": lambda *a: None,
                 "db": types.SimpleNamespace(
                     case=types.SimpleNamespace(c=types.SimpleNamespace(
                         case_id=None)),
                     known_fact=types.SimpleNamespace(c=types.SimpleNamespace(
                         case_id=None)),
                     unit_cost_prior=types.SimpleNamespace(
                         c=types.SimpleNamespace(country=None,
                                                 approved=None))),
                 "_priced_countries": lambda _s, countries: sorted(
                     countries or [])}
    exec(source[start:end], namespace)
    namespace["_source"] = source
    return types.SimpleNamespace(**namespace)


preflight = _preflight_module()


class _Row:
    def __init__(self, **over):
        for field in preflight.INPUT_FIELDS:
            setattr(self, field, None)
        self.in_scope_countries = over.pop("countries", ["GB", "DE"])
        self.perimeter_version = over.pop("pv", 1)
        for key, value in over.items():
            setattr(self, key, value)


class _Fact:
    def __init__(self, fact_id="f1", value="340", basis="CLIENT_CONVERSATION",
                 cleared=True, corroboration="CORROBORATED"):
        self.fact_id, self.value, self.basis = fact_id, value, basis
        self.fact_class = "SITE_COUNT"
        self.rights_cleared, self.corroboration_state = cleared, corroboration


class _Session:
    """Returns the case row for a case query and the facts for a fact query.

    Crude by design: the digest reads exactly three things, and a fixture that
    modelled the ORM would test the fixture.
    """

    def __init__(self, row, facts=()):
        self.row, self.facts = row, facts

    def execute(self, _query):
        outer = self
        return types.SimpleNamespace(
            first=lambda: outer.row, all=lambda: list(outer.facts))


def _digest(row, facts=()):
    return preflight.input_digest(_Session(row, facts), "c")


def test_the_same_case_hashes_the_same_twice():
    """A digest that changed between two reads of unchanged data would
    invalidate every approval the moment it was checked."""
    assert _digest(_Row()) == _digest(_Row())


def test_reordering_a_list_is_not_a_change():
    """in_scope_countries holding ["GB","DE"] and ["DE","GB"] is the same
    scope. Treating them as different would invalidate an approval for a
    reordering, which is how a check like this gets switched off."""
    assert _digest(_Row(countries=["GB", "DE"])) == _digest(
        _Row(countries=["DE", "GB"]))


@pytest.mark.parametrize("label,row", [
    ("a country added to scope", _Row(countries=["GB", "DE", "FR"])),
    ("the perimeter advanced", _Row(pv=2)),
    ("the entity reconfirmed", _Row(entity_confirmed_by="someone else")),
    ("the currency changed", _Row(base_currency="USD")),
    ("declared spend changed", _Row(declared_spend_by_country={"GB": 1})),
])
def test_a_real_change_changes_the_digest(label, row):
    assert _digest(row) != _digest(_Row()), label


def test_a_fact_changing_its_value_changes_the_digest():
    """A known fact is an input to a condition, so the approval described the
    fact as it was."""
    before = _digest(_Row(), [_Fact(value="340")])
    after = _digest(_Row(), [_Fact(value="1840")])
    assert before != after


def test_a_fact_losing_its_rights_clearance_changes_the_digest():
    """Pre-flight blocks on uncleared prior-engagement facts, so clearance is
    part of what was approved."""
    before = _digest(_Row(), [_Fact(basis="PRIOR_ENGAGEMENT", cleared=True)])
    after = _digest(_Row(), [_Fact(basis="PRIOR_ENGAGEMENT", cleared=False)])
    assert before != after


def test_fact_order_is_not_a_change():
    """Two facts returned in a different order are the same two facts."""
    a, b = _Fact("f1", "340"), _Fact("f2", "90")
    assert _digest(_Row(), [a, b]) == _digest(_Row(), [b, a])


def test_the_workflow_moving_on_is_not_a_change():
    """`stage`, `stage_advanced_at` and the acknowledgement columns change as a
    consequence of using the report. Hashing those would invalidate it for the
    act of being approved."""
    for field in ("stage", "stage_advanced_at", "stage_advanced_by",
                  "acknowledged_by", "acknowledged_at", "archived"):
        assert field not in preflight.INPUT_FIELDS, field


def test_the_gate_refuses_a_report_computed_from_different_data():
    """The defect this exists for. The old approval described a case that no
    longer exists, and every later stage cited it."""
    source = preflight._source
    gate = source[source.index("def assert_clear_to_run"):]
    assert "input_digest(session, case_id)" in gate
    assert "no longer exists" in gate


def test_a_report_with_no_digest_is_unverifiable_not_stale():
    """An approval given in good faith should not become a block because the
    model learned to check something new."""
    source = preflight._source
    gate = source[source.index("def assert_clear_to_run"):]
    assert "if stored:" in gate, (
        "a report predating the digest must skip the check, not fail it")


def test_the_digest_is_computed_not_stored_on_read():
    """A stored staleness flag would go stale itself."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    block = api[api.index("def get_preflight"):][:1400]
    assert "preflight.input_digest(s, case_id) != stored" in block
    assert '"stale"' in block


def test_every_case_field_a_condition_reads_is_in_the_digest():
    """A field added to the case that a condition reads and the digest does not
    cover is a silent hole: the report stays valid while the thing it described
    has changed."""
    import re

    source = preflight._source
    body = source[source.index("def run(session"):source.index("def _priced_countries")]
    read = set(re.findall(r"\brow\.(\w+)", body))
    missing = sorted(read - set(preflight.INPUT_FIELDS))
    assert not missing, (
        f"preflight.run reads {missing} from the case and the digest does not "
        f"cover them")
