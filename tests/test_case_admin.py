"""Removing a case, and refusing to remove one that is a record of work.

This system retains things: a superseded fact, a failed agent run and a
refused estimate are all part of how an answer came to be. But a case created
by mistake - a typo in the entity name, a duplicate, a scratch case used to
try the interface - is not a record of anything, and leaving it in the picker
is how an analyst ends up working on the wrong one.
"""
import uuid

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import case_admin


def _case(session, **over):
    case_id = str(uuid.uuid4())
    values = dict(case_id=case_id, created_by="tester",
                  subject_entity_legal_name="Acme Global Logistics")
    values.update(over)
    session.execute(insert(db.case).values(**values))
    session.commit()
    return case_id


def test_an_empty_case_is_removed_without_ceremony(session):
    case_id = _case(session)
    out = case_admin.delete_case(session, case_id=case_id,
                                 deleted_by="Priya Raman")
    assert out["removed"] == {}
    assert session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first() is None


def test_a_case_with_content_needs_confirmation(session):
    """An accidental click should not discard a morning's research."""
    case_id = _case(session)
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class="Location footprint", subject="Acme DE", value_base=340,
        unit="sites", asserted_by="CB", basis="INDUSTRY_KNOWLEDGE",
        verifiability="PUBLICLY_VERIFIABLE"))
    session.commit()

    with pytest.raises(case_admin.CaseIsARecord, match="record"):
        case_admin.delete_case(session, case_id=case_id, deleted_by="CB")

    out = case_admin.delete_case(session, case_id=case_id, deleted_by="CB",
                                 force=True)
    assert out["removed"]["known_fact"] == 1


def test_a_published_estimate_cannot_be_deleted_even_with_force(session):
    """The snapshot is the provenance for a number that may have left the
    building. force acknowledges content; it is not a way past this."""
    case_id = _case(session)
    session.execute(insert(db.estimate_snapshot).values(
        estimate_snapshot_id=str(uuid.uuid4()), case_id=case_id,
        version_label="V0", v0_status="COMPLETE"))
    session.commit()

    for force in (False, True):
        with pytest.raises(case_admin.CaseIsARecord, match="Archive"):
            case_admin.delete_case(session, case_id=case_id, deleted_by="CB",
                                   force=force)


def test_deletion_is_attributed(session):
    case_id = _case(session)
    with pytest.raises(ValueError, match="name who is doing it"):
        case_admin.delete_case(session, case_id=case_id, deleted_by="  ")


def test_deletion_leaves_no_orphans(session):
    """Half-deleting a case - the case row gone, its agent runs orphaned -
    leaves rows nobody can trace to anything, which is worse than either
    keeping it or removing it properly."""
    case_id = _case(session)
    session.execute(insert(db.agent_run).values(
        agent_run_id=str(uuid.uuid4()), case_id=case_id, agent_id="LLM-01",
        mode="LIVE", status="SUCCEEDED"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, domain_no=2,
        domain_name="Location footprint", disposition="BENCHMARK_PRIOR"))
    session.commit()

    case_admin.delete_case(session, case_id=case_id, deleted_by="CB",
                           force=True)
    for table in (db.agent_run, db.domain_disposition):
        assert session.execute(select(table).where(
            table.c.case_id == case_id)).first() is None


def test_archiving_keeps_everything_and_is_reversible(session):
    """The route for a case that did produce something. The reason for
    archiving is usually "not now" rather than "never"."""
    case_id = _case(session)
    case_admin.archive_case(session, case_id=case_id, archived_by="CB")
    row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).one()
    assert row.archived is True and row.archived_by == "CB"

    case_admin.archive_case(session, case_id=case_id, archived_by="CB",
                            archived=False)
    row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).one()
    assert row.archived is False


def test_every_table_carrying_a_case_id_is_in_the_delete_list():
    """A table added later that nobody adds here leaves orphans behind."""
    from app import db as dbmod
    carrying = {t.name for t in dbmod.metadata.sorted_tables
                if "case_id" in t.columns and t.name != "engagement_case"}
    missing = sorted(carrying - set(case_admin.DEPENDENTS))
    assert not missing, f"tables that would be orphaned by a delete: {missing}"


# ------------------------------- C-04: cross-case resource contamination
def _succeeded_simulation(session, case_id: str) -> str:
    sim_id = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=sim_id, case_id=case_id, seed=42, ensemble_size=1,
        status="SUCCEEDED", model_version="sim-1.5.0",
        params={"footprint": [{"country": "DE", "archetype": "STORE",
                               "sites": 10}]},
        output={"sites": 10, "products": [], "scope": []}))
    session.commit()
    return sim_id


def _fact(session, case_id: str) -> str:
    fact_id = str(uuid.uuid4())
    session.execute(insert(db.known_fact).values(
        known_fact_id=fact_id, case_id=case_id,
        fact_class="Location footprint", subject="Acme", value_base=340,
        unit="sites", asserted_by="tester", basis="CLIENT_CONVERSATION",
        verifiability="PUBLICLY_VERIFIABLE", corroboration_state="PENDING"))
    session.commit()
    return fact_id


def test_an_estimate_cannot_consume_another_cases_simulation(session, client):
    """Audit finding C-04, demonstrated: case A's path with case B's
    simulation id built A's estimate from B's estate, returned B's topology and
    site counts, and attributed them to A.

    404 rather than 403: whether a simulation exists on another case is not
    something a caller without access to that case should be able to learn."""
    case_a = _case(session, subject_entity_legal_name="Alpha Ltd")
    case_b = _case(session, subject_entity_legal_name="Beta GmbH")
    sim_b = _succeeded_simulation(session, case_b)

    r = client.post(f"/v1/outside-in/cases/{case_a}/estimates:run",
                    json={"method": "BUILD_UP",
                          "simulation_run_id": sim_b,
                          "users": 100, "ops_cost_per_site_base": 900})
    assert r.status_code == 404, (
        f"case {case_a[:8]} accepted case {case_b[:8]}'s simulation: "
        f"{r.status_code} {r.text[:200]}")
    assert "on this case" in r.text


@pytest.mark.parametrize("route,method,payload", [
    ("known-facts/{fact}:corroborate", "post", {"corroborated_by": "CB"}),
    ("known-facts/{fact}:clear-rights", "post", {"cleared_by": "CB"}),
    ("known-facts/{fact}:void", "post", {"voided_by": "CB"}),
    ("known-facts/{fact}/provenance", "get", None),
])
def test_a_fact_cannot_be_acted_on_from_another_case(session, client, route,
                                                     method, payload):
    """The same defect in a weaker form: these four routes took no case at all,
    so any fact on any case could be corroborated, rights-cleared, voided or
    have its provenance read by id alone."""
    case_a = _case(session, subject_entity_legal_name="Alpha Ltd")
    case_b = _case(session, subject_entity_legal_name="Beta GmbH")
    fact_b = _fact(session, case_b)

    path = f"/v1/outside-in/cases/{case_a}/" + route.format(fact=fact_b)
    r = (client.get(path) if method == "get"
         else client.post(path, json=payload))
    assert r.status_code == 404, (
        f"{route} let case {case_a[:8]} act on case {case_b[:8]}'s fact")
