"""Exporting and restoring what a user typed.

Nothing in this application deletes a known fact: the one delete path refuses
any fact carrying a subject and a value, register commits, and the database
sits in a named volume that survives a rebuild. What does not survive is
`docker compose down -v` - a command that appears in this project's own
troubleshooting notes as a way past a schema problem.

Someone typing what they know into a register and losing it to a maintenance
instruction is a failure of this system whichever layer removed the row.
"""
import uuid

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import case_export


def _populated_case(session):
    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="CB",
        subject_entity_legal_name="Adolf Wuerth GmbH & Co. KG",
        country_of_domicile="DE", in_scope_countries=["DE", "FR"],
        entity_aliases=["Wuerth", "Wuerth Group"]))
    for value, subject in ((1000, "Wuerth"), (500, "Adolf Wuerth GmbH & Co. KG")):
        session.execute(insert(db.known_fact).values(
            known_fact_id=str(uuid.uuid4()), case_id=case_id,
            fact_class="Location footprint", subject=subject,
            value_base=value, unit="sites", asserted_by="CB",
            basis="THIRD_PARTY_REPORT", verifiability="PUBLICLY_VERIFIABLE"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, domain_no=2,
        domain_name="Location footprint", disposition="ANALYST_ASSERTED_PRIOR"))
    session.commit()
    return case_id


def test_an_export_carries_the_facts_a_person_typed(session):
    case_id = _populated_case(session)
    out = case_export.export_case(session, case_id)
    assert out["counts"]["known_facts"] == 2
    assert out["counts"]["domain_dispositions"] == 1
    assert out["case"]["entity_aliases"] == ["Wuerth", "Wuerth Group"]
    subjects = {f["subject"] for f in out["known_facts"]}
    assert subjects == {"Wuerth", "Adolf Wuerth GmbH & Co. KG"}


def test_a_decimal_survives_the_round_trip(session):
    """A site count that comes back as 1000.0000 and a site count that comes
    back as a string are both fine; one that comes back as None is not."""
    case_id = _populated_case(session)
    out = case_export.export_case(session, case_id)
    values = sorted(float(f["value_base"]) for f in out["known_facts"])
    assert values == [500.0, 1000.0]


def test_restoring_into_an_empty_database_returns_the_facts(session):
    case_id = _populated_case(session)
    payload = case_export.export_case(session, case_id)

    session.execute(db.known_fact.delete())
    session.execute(db.domain_disposition.delete())
    session.execute(db.case.delete())
    session.commit()

    result = case_export.import_case(session, payload, new_case=False)
    assert result["case_id"] == case_id
    assert result["known_facts"]["restored"] == 2
    rows = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_id)).all()
    assert len(rows) == 2


def test_restoring_beside_the_original_does_not_collide(session):
    """The common case is a restore after partial loss, where some of the
    original may still be present."""
    case_id = _populated_case(session)
    payload = case_export.export_case(session, case_id)

    result = case_export.import_case(session, payload, new_case=True)
    assert result["case_id"] != case_id
    assert result["known_facts"]["restored"] == 2
    assert session.execute(select(db.known_fact)).all().__len__() == 4


def test_an_import_never_overwrites_an_existing_fact(session):
    """A restore is a recovery. Silently replacing a fact someone has since
    corroborated would be the same class of loss this exists to prevent."""
    case_id = _populated_case(session)
    payload = case_export.export_case(session, case_id)
    result = case_export.import_case(session, payload, new_case=False)
    assert result["known_facts"]["restored"] == 0
    assert result["known_facts"]["skipped_existing"] == 2


def test_an_unknown_format_is_refused(session):
    with pytest.raises(ValueError, match="unrecognised export format"):
        case_export.import_case(session, {"format": "something-else"})


def test_agent_runs_and_estimates_are_not_carried(session):
    """They are reproducible from the inputs, and their provenance points at a
    database that no longer exists - moving them would carry records whose
    audit chain the move itself had broken."""
    case_id = _populated_case(session)
    out = case_export.export_case(session, case_id)
    for absent in ("agent_runs", "estimate_snapshots", "simulation_runs"):
        assert absent not in out
