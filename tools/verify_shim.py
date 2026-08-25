"""Verify the offline SQLAlchemy shim against behaviours the real library guarantees.

Run this BEFORE trusting any result from `run_pure_tests.py`. If the shim is
wrong, application tests would pass or fail for reasons that have nothing to do
with the application - which is worse than not running them at all. Every check
below is a property the real library has, chosen because the application or its
tests depend on it.

    python tools/verify_shim.py
"""
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools" / "offline_shims"))

from sqlalchemy import (Boolean, Column, Date, DateTime, Integer, JSON,  # noqa: E402
                        MetaData, Numeric, String, Table, Text,
                        UniqueConstraint, create_engine, delete, insert,
                        select, sessionmaker, text, update)
from sqlalchemy.exc import IntegrityError, NoResultFound  # noqa: E402

checks, failures = [], []


def check(name):
    def deco(fn):
        try:
            fn()
            checks.append(name)
        except Exception as e:                       # noqa: BLE001
            failures.append((name, f"{type(e).__name__}: {e}"))
        return fn
    return deco


md = MetaData()
t = Table(
    "thing", md,
    Column("id", String(36), primary_key=True),
    Column("name", String(64), nullable=False),
    Column("qty", Integer),
    Column("payload", JSON),
    Column("at", DateTime(timezone=True)),
    Column("on", Date),
    Column("flag", Boolean),
    Column("amount", Numeric(12, 4)),
    Column("uniq", String(32)),
    UniqueConstraint("uniq", name="uq_thing_uniq"),
    schema="audit",
)
eng = create_engine("sqlite://")
md.create_all(eng)
S = sessionmaker(bind=eng)
s = S()


def _row(**kw):
    base = dict(id=str(uuid.uuid4()), name="n", qty=1, payload=None, at=None,
                on=None, flag=None, amount=None, uniq=str(uuid.uuid4()))
    base.update(kw)
    s.execute(insert(t).values(**base))
    s.commit()
    return base


@check("insert then select round-trips a row")
def _():
    r = _row(name="alpha", qty=7)
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert got.name == "alpha" and got.qty == 7, got


@check("JSON column round-trips a dict, not a string")
def _():
    r = _row(payload={"a": [1, 2], "b": {"c": "d"}})
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert isinstance(got.payload, dict), type(got.payload)
    assert got.payload["b"]["c"] == "d"


@check("DateTime round-trips as a datetime, not a string")
def _():
    now = datetime.now(timezone.utc)
    r = _row(at=now)
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert isinstance(got.at, datetime), type(got.at)
    assert abs((got.at - now).total_seconds()) < 1


@check("Date round-trips as a date")
def _():
    r = _row(on=date(2026, 5, 1))
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert got.on == date(2026, 5, 1), got.on


@check("Boolean round-trips as a bool")
def _():
    r = _row(flag=True)
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert got.flag is True, repr(got.flag)


@check("NULL stays None for every typed column")
def _():
    r = _row()
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert got.payload is None and got.at is None and got.on is None


@check("UNIQUE constraint is enforced by the database, raising IntegrityError")
def _():
    r = _row(uniq="collide-me")
    try:
        _row(uniq="collide-me")
    except IntegrityError:
        return
    raise AssertionError("duplicate was accepted - the constraint is not real")


@check("NOT NULL is enforced by the database")
def _():
    try:
        s.execute(insert(t).values(id=str(uuid.uuid4()), name=None,
                                   uniq=str(uuid.uuid4())))
        s.commit()
    except IntegrityError:
        return
    raise AssertionError("NULL accepted into a NOT NULL column")


@check("one() raises NoResultFound on an empty result")
def _():
    try:
        s.execute(select(t).where(t.c.id == "nope")).one()
    except NoResultFound:
        return
    raise AssertionError("one() returned instead of raising")


@check("one_or_none() returns None rather than raising")
def _():
    assert s.execute(select(t).where(t.c.id == "nope")).one_or_none() is None


@check("first() returns None on empty, a row otherwise")
def _():
    assert s.execute(select(t).where(t.c.id == "nope")).first() is None
    r = _row()
    assert s.execute(select(t).where(t.c.id == r["id"])).first() is not None


@check("._mapping gives a dict of the selected columns")
def _():
    r = _row(name="mapped")
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    m = got._mapping
    assert isinstance(m, dict) and m["name"] == "mapped"


@check("column-list select returns only those columns")
def _():
    r = _row(name="narrow")
    got = s.execute(select(t.c.id, t.c.name).where(t.c.id == r["id"])).one()
    assert set(got._mapping) == {"id", "name"}, got._mapping


@check("update().where().values() changes only matching rows")
def _():
    a, b = _row(name="keep"), _row(name="change")
    s.execute(update(t).where(t.c.id == b["id"]).values(name="changed"))
    s.commit()
    assert s.execute(select(t).where(t.c.id == a["id"])).one().name == "keep"
    assert s.execute(select(t).where(t.c.id == b["id"])).one().name == "changed"


@check("delete().where() removes only matching rows")
def _():
    a, b = _row(), _row()
    s.execute(delete(t).where(t.c.id == b["id"]))
    s.commit()
    assert s.execute(select(t).where(t.c.id == b["id"])).first() is None
    assert s.execute(select(t).where(t.c.id == a["id"])).first() is not None


@check("multiple where() clauses AND together")
def _():
    r = _row(name="both", qty=42)
    assert s.execute(select(t).where(t.c.name == "both", t.c.qty == 42)).first()
    assert s.execute(select(t).where(t.c.name == "both", t.c.qty == 41)).first() is None


@check("in_() matches a set and an empty list matches nothing")
def _():
    r = _row(name="inlist")
    assert s.execute(select(t).where(t.c.name.in_(["inlist", "x"]))).first()
    assert s.execute(select(t).where(t.c.name.in_([]))).first() is None


@check("is_(None) and isnot(None) discriminate NULLs")
def _():
    r = _row(qty=None)
    ids = {x.id for x in s.execute(select(t.c.id).where(t.c.qty.is_(None))).all()}
    assert r["id"] in ids
    ids2 = {x.id for x in s.execute(select(t.c.id).where(t.c.qty.isnot(None))).all()}
    assert r["id"] not in ids2


@check("order_by desc() actually reverses")
def _():
    s.execute(delete(t))
    s.commit()
    for i in (1, 3, 2):
        _row(qty=i)
    got = [r.qty for r in s.execute(select(t.c.qty).order_by(t.c.qty.desc())).all()]
    assert got == [3, 2, 1], got


@check("limit() bounds the result")
def _():
    got = s.execute(select(t.c.qty).order_by(t.c.qty.desc()).limit(2)).all()
    assert len(got) == 2, len(got)


@check("bulk insert of a list writes every row")
def _():
    s.execute(delete(t))
    s.commit()
    s.execute(insert(t), [
        {"id": str(uuid.uuid4()), "name": f"bulk{i}", "qty": i,
         "uniq": str(uuid.uuid4())} for i in range(5)])
    s.commit()
    assert len(s.execute(select(t)).all()) == 5


@check("a column default is applied when the value is omitted")
def _():
    md2 = MetaData()
    t2 = Table("defaulted", md2,
               Column("id", String(36), primary_key=True),
               Column("n", Integer, default=99),
               schema="audit")
    md2.create_all(eng)
    s.execute(insert(t2).values(id="d1"))
    s.commit()
    assert s.execute(select(t2).where(t2.c.id == "d1")).one().n == 99


@check("a callable default is invoked")
def _():
    md3 = MetaData()
    t3 = Table("calldefault", md3,
               Column("id", String(36), primary_key=True),
               Column("when", DateTime(timezone=True),
                      default=lambda: datetime.now(timezone.utc)),
               schema="audit")
    md3.create_all(eng)
    s.execute(insert(t3).values(id="c1"))
    s.commit()
    assert isinstance(s.execute(select(t3).where(t3.c.id == "c1")).one().when,
                      datetime)


@check("schemas are separate namespaces, not one flat table space")
def _():
    mdA, mdB = MetaData(), MetaData()
    a = Table("same_name", mdA, Column("id", String(8), primary_key=True),
              Column("side", String(8)), schema="audit")
    b = Table("same_name", mdB, Column("id", String(8), primary_key=True),
              Column("side", String(8)), schema="analysis")
    mdA.create_all(eng); mdB.create_all(eng)
    s.execute(insert(a).values(id="1", side="audit"))
    s.execute(insert(b).values(id="1", side="analysis"))
    s.commit()
    assert s.execute(select(a).where(a.c.id == "1")).one().side == "audit"
    assert s.execute(select(b).where(b.c.id == "1")).one().side == "analysis"


@check("raw text() executes and returns rows")
def _():
    got = s.execute(text("SELECT 1 AS one")).all()
    assert got and got[0].one == 1


@check("drop_all then create_all leaves an empty but usable table")
def _():
    _row()
    md.drop_all(eng)
    md.create_all(eng)
    assert s.execute(select(t)).all() == []
    _row(name="after-reset")
    assert len(s.execute(select(t)).all()) == 1


@check("Numeric round-trips as Decimal")
def _():
    from decimal import Decimal
    r = _row(amount=Decimal("12.3400"))
    got = s.execute(select(t).where(t.c.id == r["id"])).one()
    assert isinstance(got.amount, Decimal), type(got.amount)


@check("indexes on schema-qualified tables are created (SQLite qualifies the "
       "INDEX, not the table)")
def _():
    from sqlalchemy import Index
    md4 = MetaData()
    t4 = Table("indexed", md4,
               Column("id", String(8), primary_key=True),
               Column("k", String(8), index=True),
               Column("a", String(8)), Column("b", String(8)),
               Index("ix_indexed_ab", "a", "b"),
               schema="analysis")
    md4.create_all(eng)          # a syntax error here is the bug this catches
    s.execute(insert(t4).values(id="1", k="x", a="p", b="q"))
    s.commit()
    assert s.execute(select(t4).where(t4.c.k == "x")).one().id == "1"


@check("a UNIQUE Index is enforced, not merely created")
def _():
    from sqlalchemy import Index
    md5 = MetaData()
    t5 = Table("uniqindexed", md5,
               Column("id", String(8), primary_key=True),
               Column("k", String(8)),
               Index("ix_uniq_k", "k", unique=True),
               schema="analysis")
    md5.create_all(eng)
    s.execute(insert(t5).values(id="1", k="dup")); s.commit()
    try:
        s.execute(insert(t5).values(id="2", k="dup")); s.commit()
    except IntegrityError:
        return
    raise AssertionError("unique index did not enforce")


@check("a composite primary key is created and enforced")
def _():
    md6 = MetaData()
    t6 = Table("composite", md6,
               Column("a", String(8), primary_key=True),
               Column("b", String(8), primary_key=True),
               Column("v", String(8)), schema="reference")
    md6.create_all(eng)          # "more than one primary key" is the bug here
    s.execute(insert(t6).values(a="1", b="1", v="x"))
    s.execute(insert(t6).values(a="1", b="2", v="y"))
    s.commit()
    try:
        s.execute(insert(t6).values(a="1", b="1", v="z")); s.commit()
    except IntegrityError:
        assert s.execute(select(t6).where(t6.c.a == "1")).all().__len__() == 2
        return
    raise AssertionError("composite key did not enforce uniqueness")


@check("inspect().has_table answers truthfully for present and absent tables")
def _():
    from sqlalchemy import inspect
    insp = inspect(eng)
    assert insp.has_table("thing", schema="audit") is True
    assert insp.has_table("definitely_not_here", schema="audit") is False
    # A Connection must work wherever an Engine does - the real library allows
    # either, and migrations.py passes a Connection.
    with eng.begin() as conn:
        assert inspect(conn).has_table("thing", schema="audit") is True


@check("inspect() accepts a Connection for create_all/drop_all/get_columns too")
def _():
    from sqlalchemy import inspect
    with eng.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("thing", schema="audit")}
    assert "payload" in cols and "uniq" in cols, cols


@check("a Connection exposes .dialect like an Engine (migrations branch on it)")
def _():
    with eng.begin() as conn:
        assert conn.dialect.name == "sqlite"
    assert eng.dialect.name == "sqlite"


@check("get_columns reports nullability, which migrations branch on")
def _():
    from sqlalchemy import inspect
    cols = {c["name"]: c for c in inspect(eng).get_columns("thing", schema="audit")}
    assert cols["name"]["nullable"] is False, cols["name"]
    assert cols["qty"]["nullable"] is True, cols["qty"]


@check("an unsupported construct refuses rather than guessing")
def _():
    from sqlalchemy import _Unsupported
    try:
        select("not a table")
    except _Unsupported:
        return
    raise AssertionError("shim accepted something it does not implement")


print("=" * 68)
print(f"SHIM VERIFICATION: {len(checks)} passed, {len(failures)} FAILED")
print("=" * 68)
if failures:
    for name, err in failures:
        print(f"\n  FAIL  {name}\n        {err}")
    print("\nThe shim is not trustworthy. Do NOT read run_pure_tests.py results "
          "as evidence about the application until these pass.")
    sys.exit(1)
print("\nEvery property checked here is one the real library guarantees and the "
      "application depends on. Constraints, types and NULL handling are enforced "
      "by real sqlite3, not by the shim.")
