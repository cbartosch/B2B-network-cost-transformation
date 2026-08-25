"""A SQLAlchemy Core subset backed by real stdlib sqlite3.

WHY THIS IS NOT A FAKE
----------------------
Every statement is compiled to real SQL and executed by real sqlite3 against
real ATTACHed in-memory schemas. Unique constraints, NOT NULL, primary keys and
type affinity are enforced by the database, not by this file. That matters: the
DB control tests exist to prove *database* behaviour, so the database has to be
real even when SQLAlchemy is not installed.

WHAT IS NOT REAL
----------------
The query-*building* layer is mine and covers only what this codebase uses:
select / insert / update / delete, where with == != in_ is_ isnot, order_by,
limit, bulk insert, and the result accessors. No ORM, no relationships, no
joins, no subqueries, no pooling.

Anything outside that surface raises `_Unsupported` rather than returning a
plausible result. A silent wrong answer would be worse than no answer: it would
launder an untested claim into a passing test.

`tools/verify_shim.py` checks this layer against behaviours the real library
guarantees, so a defect here surfaces as a shim failure rather than as a
misleading application result.
"""
import datetime as _dt
import json as _json
import sqlite3
import threading
from decimal import Decimal

from .exc import IntegrityError, NoResultFound


class _Unsupported(RuntimeError):
    """Deliberately loud: this shim refuses rather than approximates."""


# --------------------------------------------------------------- types
class _Type:
    sql = "TEXT"
    def __init__(self, *a, **k): pass
    def compile(self, *a, **k): return self.sql


class String(_Type): sql = "TEXT"
class Text(_Type): sql = "TEXT"
class Integer(_Type): sql = "INTEGER"
class Boolean(_Type): sql = "INTEGER"
class Date(_Type): sql = "DATE"
class DateTime(_Type): sql = "TIMESTAMP"
class Numeric(_Type): sql = "NUMERIC"
class JSON(_Type): sql = "JSON"


def _mk_type(t):
    if isinstance(t, _Type):
        return t
    if isinstance(t, type) and issubclass(t, _Type):
        return t()
    return _Type()


def _coerce_out(value, type_):
    if value is None:
        return None
    if isinstance(type_, JSON):
        return _json.loads(value) if isinstance(value, str) else value
    if isinstance(type_, DateTime):
        if isinstance(value, str):
            try:
                return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        return value
    if isinstance(type_, Date):
        if isinstance(value, str):
            try:
                return _dt.date.fromisoformat(value)
            except ValueError:
                return value
        return value
    if isinstance(type_, Boolean):
        return bool(value)
    if isinstance(type_, Numeric):
        return Decimal(str(value))
    return value


def _coerce_in(value, type_):
    if value is None:
        return None
    if isinstance(type_, JSON):
        return _json.dumps(value)
    if isinstance(type_, (DateTime, Date)):
        if isinstance(value, (_dt.datetime, _dt.date)):
            return value.isoformat()
        return value
    if isinstance(type_, Boolean):
        return 1 if value else 0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return _json.dumps(value)
    return value


# --------------------------------------------------------------- clauses
class _Clause:
    def __init__(self, parts=None, params=None):
        self.parts = list(parts or [])
        self.params = list(params or [])
    def sql(self):
        return " AND ".join(self.parts)


def _combine(clauses):
    parts, params = [], []
    for c in clauses:
        if c is None:
            continue
        if not isinstance(c, _Clause):
            raise _Unsupported(f"unsupported WHERE expression: {c!r}")
        parts.extend(c.parts)
        params.extend(c.params)
    return _Clause(parts, params)


class _OrderBy:
    def __init__(self, col, descending): self.col, self.descending = col, descending


class Column:
    def __init__(self, name=None, type_=None, *args, **kw):
        self.name = name
        self.type = _mk_type(type_)
        self.primary_key = kw.get("primary_key", False)
        self.nullable = kw.get("nullable", True)
        self.default = kw.get("default")
        self.index = kw.get("index", False)
        self.table = None

    def _ref(self):
        if self.table is None:
            return f'"{self.name}"'
        return f'{self.table._qual}."{self.name}"'

    def _cmp(self, op, other):
        if isinstance(other, Column):
            return _Clause([f"{self._ref()} {op} {other._ref()}"], [])
        return _Clause([f"{self._ref()} {op} ?"], [_coerce_in(other, self.type)])

    def __eq__(self, other): return self._cmp("=", other)
    def __ne__(self, other): return self._cmp("!=", other)
    def __gt__(self, other): return self._cmp(">", other)
    def __lt__(self, other): return self._cmp("<", other)
    def __ge__(self, other): return self._cmp(">=", other)
    def __le__(self, other): return self._cmp("<=", other)
    def __hash__(self): return id(self)

    def in_(self, values):
        vals = list(values)
        if not vals:
            return _Clause(["0 = 1"], [])
        marks = ", ".join("?" for _ in vals)
        return _Clause([f"{self._ref()} IN ({marks})"],
                       [_coerce_in(v, self.type) for v in vals])

    def is_(self, other):
        if other is None:
            return _Clause([f"{self._ref()} IS NULL"], [])
        if other is True:
            return _Clause([f"{self._ref()} = 1"], [])
        if other is False:
            return _Clause([f"{self._ref()} = 0"], [])
        return self._cmp("IS", other)

    def isnot(self, other):
        if other is None:
            return _Clause([f"{self._ref()} IS NOT NULL"], [])
        return self._cmp("IS NOT", other)
    is_not = isnot

    def desc(self): return _OrderBy(self, True)
    def asc(self): return _OrderBy(self, False)


class _Cols:
    def __init__(self): self._c = {}
    def _add(self, col): self._c[col.name] = col
    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, "_c")[name]
        except KeyError:
            raise AttributeError(f"no column {name!r} on this table")
    def __getitem__(self, name): return self._c[name]
    def __contains__(self, name): return name in self._c
    def __iter__(self): return iter(self._c.values())
    def keys(self): return list(self._c)


class ForeignKey:
    def __init__(self, target=None, *a, **k): self.target = target


class UniqueConstraint:
    def __init__(self, *cols, **kw):
        self.cols = [c for c in cols if isinstance(c, str)]
        self.name = kw.get("name")


class Index:
    def __init__(self, name=None, *cols, **kw):
        self.name, self.cols = name, cols
        self.unique = kw.get("unique", False)


class Table:
    def __init__(self, name, metadata, *args, **kw):
        self.name = name
        self.schema = kw.get("schema")
        self.metadata = metadata
        self.c = _Cols()
        self.constraints = []
        self._order = []
        for a in args:
            if isinstance(a, Column):
                a.table = self
                self.c._add(a)
                self._order.append(a)
            elif isinstance(a, (UniqueConstraint, Index)):
                self.constraints.append(a)
        self.columns = self.c
        if metadata is not None:
            metadata._tables[f"{self.schema}.{name}"] = self

    @property
    def _qual(self):
        return f'"{self.schema}"."{self.name}"' if self.schema else f'"{self.name}"'

    def _ddl(self):
        cols = []
        pks = [c for c in self._order if c.primary_key]
        # SQLite rejects two column-level PRIMARY KEYs; a composite key has to
        # be a table constraint. reference.threshold is keyed (set_name, key).
        composite = len(pks) > 1
        for c in self._order:
            bits = [f'"{c.name}"', c.type.sql]
            if c.primary_key and not composite:
                bits.append("PRIMARY KEY")
            elif not c.nullable and not c.primary_key:
                bits.append("NOT NULL")
            cols.append(" ".join(bits))
        if composite:
            cols.append("PRIMARY KEY (" + ", ".join(f'"{c.name}"' for c in pks) + ")")
        for con in self.constraints:
            if isinstance(con, UniqueConstraint) and con.cols:
                cols.append("UNIQUE (" + ", ".join(f'"{n}"' for n in con.cols) + ")")
        return f'CREATE TABLE IF NOT EXISTS {self._qual} ({", ".join(cols)})'

    def insert(self): return _Insert(self)
    def update(self): return _Update(self)
    def delete(self): return _Delete(self)


class MetaData:
    def __init__(self, *a, **k): self._tables = {}
    @property
    def tables(self): return self._tables

    def create_all(self, engine=None, tables=None, **k):
        eng = engine or _default_engine()
        targets = tables if tables is not None else list(self._tables.values())
        with eng._lock:
            cur = eng._conn.cursor()
            for t in targets:
                cur.execute(t._ddl())
                # SQLite qualifies the INDEX with the schema, not the table:
                # CREATE INDEX audit.ix ON tbl (...). Writing
                # CREATE INDEX ix ON audit.tbl (...) is a syntax error.
                idx_prefix = f'"{t.schema}".' if t.schema else ""
                for con in t.constraints:
                    if isinstance(con, Index) and con.name:
                        names = ", ".join(
                            f'"{getattr(c, "name", c)}"' for c in con.cols)
                        uniq = "UNIQUE " if con.unique else ""
                        cur.execute(
                            f'CREATE {uniq}INDEX IF NOT EXISTS {idx_prefix}'
                            f'"{con.name}" ON "{t.name}" ({names})')
                for c in t._order:
                    if c.index:
                        cur.execute(
                            f'CREATE INDEX IF NOT EXISTS {idx_prefix}'
                            f'"ix_{t.name}_{c.name}" ON "{t.name}" ("{c.name}")')
            eng._conn.commit()

    def drop_all(self, engine=None, tables=None, **k):
        eng = engine or _default_engine()
        targets = tables if tables is not None else list(self._tables.values())
        with eng._lock:
            cur = eng._conn.cursor()
            for t in targets:
                cur.execute(f"DROP TABLE IF EXISTS {t._qual}")
            eng._conn.commit()


# --------------------------------------------------------------- statements
class _Select:
    def __init__(self, *entities):
        self.cols, self.table = [], None
        for e in entities:
            if isinstance(e, Table):
                self.table = self.table or e
                self.cols.extend(e._order)
            elif isinstance(e, Column):
                self.table = self.table or e.table
                self.cols.append(e)
            else:
                raise _Unsupported(f"select() of {e!r} is not supported")
        self._where = _Clause()
        self._order, self._limit = [], None

    def where(self, *clauses):
        self._where = _combine([self._where] + list(clauses)); return self
    def order_by(self, *cols):
        self._order.extend(cols); return self
    def limit(self, n):
        self._limit = n; return self

    def _compile(self):
        sql = ("SELECT " + ", ".join(c._ref() for c in self.cols)
               + f" FROM {self.table._qual}")
        if self._where.parts:
            sql += " WHERE " + self._where.sql()
        if self._order:
            bits = []
            for o in self._order:
                if isinstance(o, _OrderBy):
                    bits.append(f"{o.col._ref()} {'DESC' if o.descending else 'ASC'}")
                elif isinstance(o, Column):
                    bits.append(f"{o._ref()} ASC")
            sql += " ORDER BY " + ", ".join(bits)
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
        return sql, list(self._where.params)


class _Insert:
    def __init__(self, table): self.table, self._values = table, None
    def values(self, **kw): self._values = kw; return self
    def _compile(self, row=None):
        data = dict(row if row is not None else (self._values or {}))
        for c in self.table._order:
            if c.name not in data and c.default is not None:
                data[c.name] = c.default() if callable(c.default) else c.default
        names = ", ".join(f'"{k}"' for k in data)
        marks = ", ".join("?" for _ in data)
        params = [_coerce_in(v, self.table.c[k].type) if k in self.table.c else v
                  for k, v in data.items()]
        return f"INSERT INTO {self.table._qual} ({names}) VALUES ({marks})", params


class _Update:
    def __init__(self, table):
        self.table, self._values, self._where = table, {}, _Clause()
    def values(self, **kw): self._values.update(kw); return self
    def where(self, *clauses):
        self._where = _combine([self._where] + list(clauses)); return self
    def _compile(self):
        sets = ", ".join(f'"{k}" = ?' for k in self._values)
        params = [_coerce_in(v, self.table.c[k].type) if k in self.table.c else v
                  for k, v in self._values.items()]
        sql = f"UPDATE {self.table._qual} SET {sets}"
        if self._where.parts:
            sql += " WHERE " + self._where.sql()
            params += self._where.params
        return sql, params


class _Delete:
    def __init__(self, table): self.table, self._where = table, _Clause()
    def where(self, *clauses):
        self._where = _combine([self._where] + list(clauses)); return self
    def _compile(self):
        sql, params = f"DELETE FROM {self.table._qual}", []
        if self._where.parts:
            sql += " WHERE " + self._where.sql()
            params = list(self._where.params)
        return sql, params


def select(*a, **k): return _Select(*a)
def insert(t, *a, **k): return _Insert(t)
def update(t, *a, **k): return _Update(t)
def delete(t, *a, **k): return _Delete(t)


class _Text:
    def __init__(self, s): self.s = s
def text(s): return _Text(s)


# --------------------------------------------------------------- results
class _Row:
    __slots__ = ("_d",)
    def __init__(self, d): object.__setattr__(self, "_d", d)
    def __getattr__(self, name):
        d = object.__getattribute__(self, "_d")
        if name in d:
            return d[name]
        raise AttributeError(name)
    @property
    def _mapping(self): return dict(object.__getattribute__(self, "_d"))
    def __getitem__(self, i):
        d = object.__getattribute__(self, "_d")
        return list(d.values())[i] if isinstance(i, int) else d[i]
    def __iter__(self): return iter(object.__getattribute__(self, "_d").values())
    def __repr__(self): return f"Row({object.__getattribute__(self, '_d')})"


class _Result:
    def __init__(self, rows, rowcount=0):
        self._rows, self.rowcount = list(rows), rowcount
    def all(self): return list(self._rows)
    def first(self): return self._rows[0] if self._rows else None
    def one(self):
        if not self._rows:
            raise NoResultFound("No row was found when exactly one was required")
        if len(self._rows) > 1:
            raise _Unsupported("multiple rows returned for one()")
        return self._rows[0]
    def one_or_none(self):
        if len(self._rows) > 1:
            raise _Unsupported("multiple rows returned for one_or_none()")
        return self._rows[0] if self._rows else None
    def scalar(self):
        if not self._rows:
            return None
        return list(object.__getattribute__(self._rows[0], "_d").values())[0]
    def fetchall(self): return self.all()
    def __iter__(self): return iter(self._rows)
    def __len__(self): return len(self._rows)


# --------------------------------------------------------------- engine
class _URL:
    def __init__(self, url): self._u = url
    def get_backend_name(self): return self._u.split(":", 1)[0].split("+")[0]
    def __str__(self): return self._u


SCHEMA_NAMES = ("engagement", "outside_in", "market", "reference",
                "benchmark", "analysis", "agent_runtime", "audit")


class _Engine:
    def __init__(self, url="sqlite://"):
        self.url = _URL(url)
        self._lock = threading.RLock()
        if self.url.get_backend_name() != "sqlite":
            raise _Unsupported(
                "this shim backs sqlite only; a Postgres URL needs the real library")
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        for name in SCHEMA_NAMES:
            self._conn.execute(f"ATTACH DATABASE ':memory:' AS {name}")
        self.dialect = type("d", (), {"name": "sqlite"})()

    def connect(self): return _Connection(self)
    def begin(self): return _Connection(self)
    def dispose(self): pass


class _Connection:
    """A connection delegates to its engine's real sqlite3 connection.

    `_conn` and `_lock` are exposed because the application passes a
    Connection where an Engine is equally valid in the real library -
    `inspect(conn)`, `metadata.create_all(conn)` and `drop_all(conn)` all
    accept either. Without this the shim raised AttributeError on '_conn',
    which looked like an application defect and was not.
    """
    def __init__(self, engine): self.engine = engine
    @property
    def _conn(self): return self.engine._conn
    @property
    def _lock(self): return self.engine._lock
    @property
    def dialect(self):
        """migrations.py branches on dialect.name to emit Postgres-only DDL.
        A Connection exposes it in the real library exactly as an Engine does."""
        return self.engine.dialect
    def __enter__(self): return self
    def __exit__(self, exc_type, *a):
        if exc_type is None:
            self.engine._conn.commit()
        else:
            self.engine._conn.rollback()
        return False
    def execute(self, stmt, params=None): return _execute(self.engine, stmt, params)
    def commit(self): self.engine._conn.commit()


_ENGINES = []


def _default_engine():
    if not _ENGINES:
        raise _Unsupported("no engine has been created")
    return _ENGINES[-1]


def create_engine(url="sqlite://", *a, **k):
    eng = _Engine(url if isinstance(url, str) else "sqlite://")
    _ENGINES.append(eng)
    return eng


def _execute(engine, stmt, params=None):
    with engine._lock:
        cur = engine._conn.cursor()
        try:
            if isinstance(stmt, _Text):
                cur.execute(stmt.s, params or [])
                if cur.description:
                    names = [d[0] for d in cur.description]
                    return _Result([_Row(dict(zip(names, r))) for r in cur.fetchall()])
                return _Result([], cur.rowcount)
            if isinstance(stmt, _Select):
                sql, p = stmt._compile()
                cur.execute(sql, p)
                rows = [_Row({c.name: _coerce_out(v, c.type)
                              for c, v in zip(stmt.cols, raw)})
                        for raw in cur.fetchall()]
                return _Result(rows)
            if isinstance(stmt, _Insert):
                if isinstance(params, list):
                    for row in params:
                        sql, p = stmt._compile(row)
                        cur.execute(sql, p)
                    return _Result([], len(params))
                sql, p = stmt._compile()
                cur.execute(sql, p)
                return _Result([], cur.rowcount)
            if isinstance(stmt, (_Update, _Delete)):
                sql, p = stmt._compile()
                cur.execute(sql, p)
                return _Result([], cur.rowcount)
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        raise _Unsupported(f"cannot execute {type(stmt).__name__}")


class _Session:
    def __init__(self, engine): self.engine = engine
    def execute(self, stmt, params=None): return _execute(self.engine, stmt, params)
    def commit(self): self.engine._conn.commit()
    def rollback(self): self.engine._conn.rollback()
    def close(self): pass
    def expire_all(self):
        """No-op, and correctly so: the real call discards the identity map so
        the next read hits the database. This shim never caches ORM objects -
        every execute() goes to sqlite3 - so there is nothing to expire. jobs.py
        calls it before re-reading a run to see another worker's commit, and
        that read is already unconditional here."""
    def flush(self): self.engine._conn.commit()
    def __enter__(self): return self
    def __exit__(self, *a): self.close(); return False


def sessionmaker(bind=None, **k):
    def factory(*a, **kk): return _Session(bind or _default_engine())
    return factory


class event:
    @staticmethod
    def listens_for(*a, **k):
        # Real listeners ATTACH schemas per connection; this engine attaches
        # them once at construction, so registration is a no-op by design.
        return lambda fn: fn


class _Inspector:
    def __init__(self, engine): self.engine = engine
    def get_table_names(self, schema=None):
        cur = self.engine._conn.cursor()
        src = f"{schema}.sqlite_master" if schema else "sqlite_master"
        cur.execute(f"SELECT name FROM {src} WHERE type='table'")
        return [r[0] for r in cur.fetchall()]
    def has_table(self, table, schema=None):
        """Missing from an earlier version of this shim, and the omission was
        the most dangerous kind. migrations._has_table wraps this in
        `except Exception: return False`, so an AttributeError here did not
        surface - it silently answered "no such table" for every table in the
        schema, and the migration logic then behaved plausibly and wrongly.
        A shim gap that raises is a nuisance; one that returns a confident
        wrong answer is the thing this whole bundle exists to prevent."""
        cur = self.engine._conn.cursor()
        src = f"{schema}.sqlite_master" if schema else "sqlite_master"
        try:
            cur.execute(f"SELECT 1 FROM {src} WHERE type='table' AND name=?",
                        (table,))
        except Exception:                                # noqa: BLE001
            return False
        return cur.fetchone() is not None

    def get_indexes(self, table, schema=None):
        cur = self.engine._conn.cursor()
        src = f"{schema}." if schema else ""
        cur.execute(f"PRAGMA {src}index_list(\"{table}\")")
        out = []
        for row in cur.fetchall():
            name, unique = row[1], bool(row[2])
            cur.execute(f"PRAGMA {src}index_info(\"{name}\")")
            cols = [r[2] for r in cur.fetchall()]
            out.append({"name": name, "unique": unique, "column_names": cols})
        return out

    def get_columns(self, table, schema=None):
        # PRAGMA takes the schema as a prefix on the pragma name, not as a
        # qualifier on the table: PRAGMA audit.table_info("t"), never
        # PRAGMA table_info("audit"."t"). Same shape as the index-DDL bug.
        cur = self.engine._conn.cursor()
        src = f"{schema}." if schema else ""
        cur.execute(f'PRAGMA {src}table_info("{table}")')
        # PRAGMA column 3 is `notnull`; the real library reports `nullable`,
        # which migrations._column_is_nullable now depends on.
        return [{"name": r[1], "type": r[2], "nullable": not r[3],
                 "primary_key": bool(r[5])} for r in cur.fetchall()]


def inspect(engine): return _Inspector(engine)
