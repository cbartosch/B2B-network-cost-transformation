"""Minimal pytest shim: raises/fixture/mark only, enough to import test modules.
Collection and execution are done by run_pure_tests.py, not by this."""
import contextlib, re as _re


class Failed(AssertionError):
    pass


class _ExcInfo:
    def __init__(self): self.value = None
    @property
    def type(self): return type(self.value)


@contextlib.contextmanager
def raises(expected, match=None):
    info = _ExcInfo()
    try:
        yield info
    except expected as e:
        info.value = e
        if match and not _re.search(match, str(e)):
            raise Failed(f"raised {expected.__name__} but message {str(e)!r} "
                         f"does not match {match!r}")
        return
    except Exception as e:
        raise Failed(f"expected {expected}, got {type(e).__name__}: {e}")
    raise Failed(f"did not raise {expected}")


def fixture(*a, **k):
    def deco(fn): fn.__is_fixture__ = True; return fn
    return deco(a[0]) if a and callable(a[0]) else deco


class _Mark:
    def __getattr__(self, name): return lambda *a, **k: (lambda fn: fn)


mark = _Mark()


def skip(reason=""): raise _Skip(reason)
class _Skip(Exception): pass
class UsageError(Exception): pass
def main(*a, **k): raise RuntimeError("use run_pure_tests.py")


def importorskip(name, *a, **k):
    try:
        return __import__(name)
    except ImportError:
        raise _Skip(f"{name} is not installed")
