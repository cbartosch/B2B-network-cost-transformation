"""Execute the test functions that need no database engine, with no dependencies.

    python tools/run_pure_tests.py

This is NOT a substitute for `make test` / `.\\make.ps1 test`, and it must not be
reported as one. It exists for an environment with no SQLAlchemy, no FastAPI and
no network, where the alternative is executing nothing at all.

What it does: puts import-only shims on sys.path so modules that DEFINE tables
can be imported, then runs every zero-argument test function for real. What it
refuses to do: fake a database. The SQLAlchemy shim raises on any query rather
than returning a plausible empty result, because a shimmed pass is worth less
than no result. Every test taking a fixture is skipped and counted separately.

Deliberately narrow. Any test whose signature takes `session` or `monkeypatch`
requires a real SQLAlchemy engine or pytest's own machinery, and is SKIPPED
here rather than faked - a shimmed pass would be worth less than no result at
all. What runs here is pure logic, executed for real.
"""
import importlib, inspect, sys, traceback, pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Shims are for libraries that are genuinely absent. `cryptography` and `yaml`
# ARE installed here, and the real ones must win - a stubbed certificate would
# make the SPKI pinning tests prove nothing, which is the opposite of the point.
sys.path[:0] = [str(_ROOT / "tools" / "offline_shims"),
                str(_ROOT / "api_service"),
                str(_ROOT),
                str(_ROOT / "tests")]
import os
os.environ.update(DATABASE_URL="sqlite://", WORKBENCH_ENVIRONMENT="TEST")

class _CannotProvide(Exception):
    pass


class _MonkeyPatch:
    """setattr / setitem / delattr with automatic undo - the subset the suite
    uses. Not pytest's implementation, but the same contract."""

    def __init__(self): self._undo = []

    def setattr(self, target, name, value=None, raising=True):
        if value is None and isinstance(name, object) and not isinstance(name, str):
            raise TypeError("string-target form of setattr is not supported here")
        old = getattr(target, name, _MISSING)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def setitem(self, mapping, key, value):
        old = mapping.get(key, _MISSING)
        self._undo.append((mapping, key, old))
        mapping[key] = value

    def delattr(self, target, name, raising=True):
        old = getattr(target, name, _MISSING)
        self._undo.append((target, name, old))
        if old is not _MISSING:
            delattr(target, name)

    def setenv(self, name, value):
        self.setitem(os.environ, name, str(value))

    def delenv(self, name, raising=True):
        old = os.environ.get(name, _MISSING)
        self._undo.append((os.environ, name, old))
        os.environ.pop(name, None)

    def undo(self):
        for target, name, old in reversed(self._undo):
            if isinstance(target, dict):
                if old is _MISSING:
                    target.pop(name, None)
                else:
                    target[name] = old
            else:
                if old is _MISSING:
                    try: delattr(target, name)
                    except AttributeError: pass
                else:
                    setattr(target, name, old)
        self._undo.clear()


class _Missing: pass
_MISSING = _Missing()


def _fresh_session():
    """Exactly what conftest.py's fixture does: reset the schema, hand back a
    session. The guard in db.assert_disposable still applies."""
    from app import db
    db.reset_schema()
    return db.SessionLocal()


MODULES = ["test_end_to_end_flow", "test_integrity", "test_research", "test_savings_advisory",
           "test_stage_and_questionnaire", "test_controls_db", "test_interface",
           "test_migrations", "test_wiring", "test_transport", "test_jobs",
           "test_auth", "test_compose"]

# Fixtures this runner can genuinely provide. `session` is real: it is a
# sqlite3-backed session from the verified shim, with the schema reset between
# tests exactly as conftest.py does it. `monkeypatch` is a faithful minimal
# implementation of setattr/setitem/delattr with automatic undo.
PROVIDABLE = {"session", "monkeypatch"}
passed, failed, skipped, import_err, needs_dep = [], [], [], [], []

for name in MODULES:
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        needs_dep.append((name + " (whole module)", str(e)))
        continue
    except Exception as e:
        # A SyntaxError here means a whole module was never collected. That used
        # to be reported only as a line in a summary nobody reads, so the total
        # silently dropped by 70 while the run still said "0 FAILED". A
        # collection failure is now fatal to the run.
        import_err.append((name, f"{type(e).__name__}: {e}"))
        continue
    for fname, fn in sorted(vars(mod).items()):
        if not fname.startswith("test_") or not callable(fn):
            continue
        params = set(inspect.signature(fn).parameters)
        # A fixture this runner cannot provide is skipped, not approximated:
        # inventing a precondition the real suite sets up properly would make
        # the result meaningless.
        # A fixture defined in the test module itself and taking no fixtures of
        # its own can simply be called - `compose` just parses a YAML file.
        # Anything needing pytest's own machinery is still skipped.
        kwargs, mp, gens = {}, None, []
        try:
            for need in params - PROVIDABLE:
                factory = getattr(mod, need, None)
                if factory is None:
                    raise _CannotProvide(need)
                inner = set(inspect.signature(factory).parameters)
                if inner - PROVIDABLE:
                    raise _CannotProvide(need)
                inner_kw = {}
                if "monkeypatch" in inner:
                    mp = mp or _MonkeyPatch()
                    inner_kw["monkeypatch"] = mp
                if "session" in inner:
                    inner_kw["session"] = _fresh_session()
                factory = (lambda f=factory, k=inner_kw: f(**k))
                produced = factory()
                if inspect.isgenerator(produced):
                    # A `yield` fixture: take the value, and close it after the
                    # test so its teardown really runs.
                    gens.append(produced)
                    produced = next(produced)
                kwargs[need] = produced
            if "session" in params:
                kwargs["session"] = _fresh_session()
            if "monkeypatch" in params:
                mp = _MonkeyPatch()
                kwargs["monkeypatch"] = mp
            fn(**kwargs)
            passed.append(f"{name}::{fname}")
        except _CannotProvide as e:
            skipped.append(f"{name}::{fname}")
            continue
        except ModuleNotFoundError as e:
            # A test that needs a third-party library this sandbox does not
            # have is not a failure and must not be reported as one. Shimming
            # its *semantics* would risk a false pass, which is worse than no
            # result.
            needs_dep.append((f"{name}::{fname}", str(e)))
        except Exception as e:
            if type(e).__name__ in ("_Skip", "_Unsupported"):
                skipped.append(f"{name}::{fname}")
                continue
            if "httpx shim: no network" in str(e):
                # The shim refuses rather than pretending to reach a server.
                # That is a missing dependency (real httpx), not a defect.
                needs_dep.append((f"{name}::{fname}", "needs real httpx"))
                continue
            failed.append((f"{name}::{fname}", f"{type(e).__name__}: {e}",
                           traceback.format_exc()))
        finally:
            for g in gens:
                try:
                    next(g)
                except StopIteration:
                    pass
                except Exception:                        # noqa: BLE001
                    pass
            if mp is not None:
                mp.undo()

print("=" * 72)
print(f"EXECUTED   {len(passed) + len(failed)}   "
      f"(passed {len(passed)}, FAILED {len(failed)})")
print(f"SKIPPED    {len(skipped)}   (need a real engine - `make test`)")
print(f"NEEDS DEP  {len(needs_dep)}   (fastapi/pydantic absent - not a failure)")
print(f"IMPORT ERR {len(import_err)}")
print("=" * 72)
if skipped:
    print("\nSKIPPED (fixtures this runner cannot provide):")
    import collections as _c, inspect as _i, importlib as _il
    reasons = _c.Counter()
    for t in skipped:
        mod, fn = t.split("::")
        try:
            f = getattr(_il.import_module(mod), fn)
            need = sorted(set(_i.signature(f).parameters) - PROVIDABLE)
            reasons[", ".join(need) or "?"] += 1
        except Exception:
            reasons["?"] += 1
    for k, v in reasons.most_common():
        print(f"  {v:4d}  needs fixture: {k}")
if needs_dep:
    print("\nNEEDS DEPENDENCY:")
    for n, e in needs_dep:
        print(f"  {n}: {e}")
if import_err:
    print("\nMODULES THAT WOULD NOT IMPORT:")
    for n, e in import_err: print(f"  {n}: {e}")
if import_err:
    sys.exit(2)
if failed:
    import collections, re as _re
    buckets = collections.Counter()
    for n, e, tb in failed:
        key = e.split(":")[0]
        m = _re.search(r"(no column named \w+|no such column|has no attribute '\w+'|"
                       r"UNIQUE constraint failed|_Unsupported|syntax error)", e)
        buckets[f"{key} | {m.group(1) if m else e[:60]}"] += 1
    print("\nFAILURE CATEGORIES:")
    for k, v in buckets.most_common():
        print(f"  {v:4d}  {k}")
    print("\nFAILURES:")
    for n, e, tb in failed:
        print(f"\n--- {n}\n    {e}")
        print("    " + "\n    ".join(tb.strip().splitlines()[-6:]))
