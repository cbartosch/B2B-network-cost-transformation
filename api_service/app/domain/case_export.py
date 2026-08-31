"""Export and import what a user entered, so it survives the environment.

Nothing in this application deletes a known fact. The delete that exists
refuses any fact carrying a subject and a value, `register` commits, and the
database sits in a named volume that survives a rebuild.

What does not survive is `docker compose down -v`, which drops the volume -
and that command was recommended in this project's own troubleshooting more
than once as a way past a schema problem. A user typing what they know into a
register, and losing it to a maintenance instruction, is a failure of this
system regardless of which layer removed the row.

So the things a person typed are exportable as a file, and restorable into an
empty database. Deliberately narrow: **only what was entered by hand**, plus
the case that gives it meaning. Agent runs, simulations and estimate snapshots
are reproducible from the inputs and their provenance is tied to a database
that no longer exists; carrying them across would move records whose audit
chain had been broken by the move itself.

The export is JSON rather than a database dump because a person should be able
to read it, diff it, and see that their facts are in there.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import insert, select

from .. import db

FORMAT_VERSION = "case-export/1.0.0"

# Only hand-entered material. See the module docstring on why derived and
# agent-produced records are left behind.
TABLES = (
    ("known_facts", "known_fact"),
    ("domain_dispositions", "domain_disposition"),
    ("evidenced_footprint", "evidenced_footprint"),
)


def _plain(value):
    """JSON-safe, and lossless for the types this schema actually uses."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def export_case(session, case_id: str) -> dict:
    """Everything a person entered on this case, as a readable document."""
    case_row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first()
    if case_row is None:
        raise LookupError(f"case {case_id} not found")

    payload = {
        "format": FORMAT_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(),
        "case": {k: _plain(v) for k, v in dict(case_row._mapping).items()},
    }
    for label, table_name in TABLES:
        table = getattr(db, table_name)
        rows = session.execute(select(table).where(
            table.c.case_id == case_id)).all()
        payload[label] = [{k: _plain(v) for k, v in dict(r._mapping).items()}
                          for r in rows]
    payload["counts"] = {label: len(payload[label]) for label, _ in TABLES}
    return payload


def import_case(session, payload: dict, *, new_case: bool = True) -> dict:
    """Restore an exported case.

    `new_case` mints fresh identifiers by default, so importing into a
    database that still holds the original does not collide with it - the
    common case being a restore after a partial loss, where some of the
    original may still be present. Set it false to restore under the original
    ids, which is what a full rebuild wants.

    Rows whose id already exists are skipped rather than overwritten. An
    import is a recovery, and silently replacing a fact that someone has since
    corroborated would be the same class of loss this exists to prevent.
    """
    if payload.get("format") != FORMAT_VERSION:
        raise ValueError(
            f"unrecognised export format {payload.get('format')!r}; expected "
            f"{FORMAT_VERSION}")
    case = dict(payload.get("case") or {})
    if not case.get("case_id"):
        raise ValueError("the export carries no case")

    old_id = case["case_id"]
    new_id = str(uuid.uuid4()) if new_case else old_id

    existing = session.execute(select(db.case.c.case_id).where(
        db.case.c.case_id == new_id)).first()
    restored = {"case_id": new_id, "case_created": False}
    if existing is None:
        case["case_id"] = new_id
        # created_at and similar server defaults are dropped so the restored
        # row is dated when it was restored, not when the lost one was made -
        # a restored case is a new record of the same content.
        case.pop("created_at", None)
        session.execute(insert(db.case).values(
            **{k: v for k, v in case.items() if k in db.case.columns}))
        restored["case_created"] = True

    for label, table_name in TABLES:
        table = getattr(db, table_name)
        pk = list(table.primary_key.columns)[0]
        added = skipped = 0
        for row in payload.get(label) or []:
            row = dict(row)
            row["case_id"] = new_id
            if new_case:
                # A fresh primary key alongside a fresh case id, so a restore
                # into a database that still holds the original does not
                # collide with it.
                row[pk.name] = str(uuid.uuid4())
            elif session.execute(select(pk).where(
                    pk == row.get(pk.name))).first():
                skipped += 1
                continue
            row.pop("created_at", None)
            session.execute(insert(table).values(
                **{k: v for k, v in row.items() if k in table.columns}))
            added += 1
        restored[label] = {"restored": added, "skipped_existing": skipped}

    session.commit()
    restored["from_case_id"] = old_id
    restored["note"] = (
        "Only hand-entered material is carried: the case, its known facts, its "
        "domain dispositions and any promoted footprint. Agent runs, "
        "simulations and estimate snapshots are not - they are reproducible "
        "from these inputs, and their provenance points at a database that no "
        "longer exists.")
    return restored
