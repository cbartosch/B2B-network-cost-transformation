"""Removing a case, and refusing to remove one that is a record of work.

This system retains things. A superseded fact, a failed agent run and a
refused estimate are all part of how an answer came to be, and deleting them
would make the audit trail a summary of what someone was willing to keep.

A case created by mistake is different. A typo in the entity name, a scratch
case used to try the interface, a duplicate - none of those is a record of
anything, and leaving them in the picker is how an analyst ends up working on
the wrong one. So removal exists, and is narrow.

**A case that has published an estimate cannot be removed.** That snapshot is
the provenance for a number that may have left the building, and its
supporting dispositions, agent runs and simulations are what make it
checkable. Archive it instead: it leaves the picker and keeps its history.

Deletion is otherwise complete. Half-deleting a case - the case row gone, its
agent runs orphaned - would leave rows nobody can trace to anything, which is
worse than either keeping it or removing it properly.
"""
from sqlalchemy import delete, func, select, update

from .. import db

# Delete order matters only for a database that enforces the references; the
# list is exhaustive rather than clever, so a table added later that nobody
# adds here shows up as an orphan the integrity test catches.
DEPENDENTS = (
    "known_fact_conflict", "known_fact", "entity_candidate",
    "questionnaire_item", "stage_readiness_report", "preflight_report",
    "domain_disposition", "evidenced_footprint", "recommendation",
    "estimate_snapshot", "simulation_run", "agent_run",
)


class CaseIsARecord(RuntimeError):
    """The case has published work and cannot be deleted."""


def summarise(session, case_id: str) -> dict:
    """What removing this case would take with it."""
    counts = {}
    for name in DEPENDENTS:
        table = getattr(db, name, None)
        if table is None:
            continue
        counts[name] = session.execute(
            select(func.count()).select_from(table)
            .where(table.c.case_id == case_id)).scalar() or 0
    return {k: v for k, v in counts.items() if v}


def delete_case(session, *, case_id: str, deleted_by: str,
                force: bool = False) -> dict:
    """Remove a case and everything that hangs off it.

    `force` is not a way past the published-estimate rule - there is no way
    past it. It only acknowledges that the case has content, so an accidental
    click cannot silently discard a morning's research.
    """
    if not (deleted_by or "").strip():
        raise ValueError("deleting a case is an act: name who is doing it")

    row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first()
    if row is None:
        raise LookupError(f"case {case_id} not found")

    published = session.execute(
        select(db.estimate_snapshot.c.estimate_snapshot_id)
        .where(db.estimate_snapshot.c.case_id == case_id)).first()
    if published:
        raise CaseIsARecord(
            "this case has published an estimate, so it is the provenance for "
            "a number that may have left the building. Archive it instead - it "
            "leaves the case picker and keeps its history.")

    contents = summarise(session, case_id)
    if contents and not force:
        raise CaseIsARecord(
            f"this case holds {sum(contents.values())} record(s) "
            f"({', '.join(f'{v} {k}' for k, v in sorted(contents.items()))}). "
            f"Confirm to remove them - an accidental click should not discard "
            f"a morning's research.")

    for name in DEPENDENTS:
        table = getattr(db, name, None)
        if table is not None:
            session.execute(delete(table).where(table.c.case_id == case_id))
    session.execute(delete(db.case).where(db.case.c.case_id == case_id))
    session.commit()
    return {"case_id": case_id, "deleted_by": deleted_by, "removed": contents,
            "subject": row.subject_entity_legal_name}


def archive_case(session, *, case_id: str, archived_by: str,
                 archived: bool = True) -> dict:
    """Take a case out of the picker without losing it.

    The route for a case that did produce something. Reversible, because the
    reason for archiving is usually "not now" rather than "never".
    """
    if not (archived_by or "").strip():
        raise ValueError("archiving a case is an act: name who is doing it")
    session.execute(update(db.case).where(db.case.c.case_id == case_id)
                    .values(archived=archived,
                            archived_by=archived_by if archived else None))
    session.commit()
    return {"case_id": case_id, "archived": archived,
            "archived_by": archived_by if archived else None}
