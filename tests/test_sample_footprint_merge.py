"""The sample driver's footprint merge, which decides what gets priced.

It lives in tools/ rather than the app, and it had no tests - which is how
it came to drop the density band on every row of every company for the
whole twenty-company set.
"""
import importlib.util
import pathlib

import pytest


def _driver():
    """Load tools/run_samples.py by path.

    It is a script rather than a package, so there is nothing to import by
    name. Skipped where the file is absent - the api image carries tools/
    but a trimmed one might not.
    """
    for root in (pathlib.Path("/app"), pathlib.Path(__file__).resolve().parents[1]):
        f = root / "tools" / "run_samples.py"
        if f.exists():
            spec = importlib.util.spec_from_file_location("_rs", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("tools/run_samples.py not present")


def _spec(rows):
    return {"slug": "t", "declared_footprint": rows}


@pytest.fixture()
def driver(monkeypatch):
    mod = _driver()
    # No database in this test: the merge's only query is for promoted
    # research rows, and the cases below are about what it does with the
    # declared side.
    monkeypatch.setattr(mod, "_promoted_rows", lambda case_id: [],
                        raising=False)
    return mod


def _merge(driver, rows, promoted=None):
    """Run the merge with the database stubbed out.

    `select` is stubbed as well as the session: the merge builds a real
    SQLAlchemy select over evidenced_footprint, and a fake table is not a
    FROM clause. The subject here is what the merge does with the rows, not
    how it asks for them.
    """
    import types

    class _Q:
        def where(self, *a, **k):
            return self

    driver.select = lambda *a, **k: _Q()

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return types.SimpleNamespace(
                all=lambda: [types.SimpleNamespace(**p)
                             for p in (promoted or [])])

    class _Cols:
        """Any column name, comparable to anything.

        The merge writes `db.evidenced_footprint.c.case_id == case_id`, and
        that expression is built before the stubbed `select` ever sees it.
        """

        def __getattr__(self, _name):
            return self

        def __eq__(self, _other):
            return True

        def __hash__(self):
            return 0

    driver.db = types.SimpleNamespace(
        SessionLocal=_Session,
        evidenced_footprint=types.SimpleNamespace(c=_Cols()))
    return driver.footprint_for_simulation("case", _spec(rows))


# ----------------------------------------------------------- the defect

def test_the_declared_density_band_reaches_the_simulation(driver):
    """serviceability is keyed (country, density_band, bearer). A row with
    no band matches nothing, takes the "silence, not a constraint" path and
    resolves DELIVERED - so dropping the band here turned the whole
    serviceability model off for twenty companies without anything saying
    so. Tesco went from 3,908 sites all DELIVERED to 25 SUBSTITUTED once
    the band arrived."""
    merged, _origin, _prov = _merge(driver, [
        {"country": "GB", "archetype": "STORE", "sites": 3700,
         "density": "SUBURBAN"},
        {"country": "GB", "archetype": "LARGE_OFFICE", "sites": 12,
         "density": "URBAN"},
    ])
    bands = {(r["country"], r["archetype"]): r.get("density") for r in merged}
    assert bands[("GB", "STORE")] == "SUBURBAN"
    assert bands[("GB", "LARGE_OFFICE")] == "URBAN"


def test_every_merged_row_carries_the_density_key(driver):
    """Present even when null, so a consumer reads a band rather than a
    KeyError and decides for itself what absence means."""
    merged, _o, _p = _merge(driver, [
        {"country": "DE", "archetype": "PLANT", "sites": 5,
         "density": "RURAL"}])
    assert all("density" in r for r in merged)


def test_a_row_with_no_band_is_reported_not_hidden(driver):
    """A researched pair has no density - evidenced_footprint stores a count
    and a source, not a band - so the gap is real and must be visible."""
    merged, _o, prov = _merge(driver, [
        {"country": "DE", "archetype": "PLANT", "sites": 5, "density": None}])
    gap = [p for p in prov if p.get("origin") == "NO_DENSITY_BAND"]
    assert gap, "a row with no density band must be reported"
    assert gap[0]["rows"] == 1 and gap[0]["sites"] == 5
    assert "serviceability" in gap[0]["note"]


def test_no_gap_row_when_every_band_is_known(driver):
    merged, _o, prov = _merge(driver, [
        {"country": "GB", "archetype": "STORE", "sites": 10,
         "density": "URBAN"}])
    assert not [p for p in prov if p.get("origin") == "NO_DENSITY_BAND"]


def test_the_band_is_never_guessed_for_a_researched_only_pair(driver):
    """A density nobody established would silently re-price the estate:
    SUBURBAN and RURAL resolve different bearers at different rates."""
    merged, _o, _p = _merge(
        driver,
        [{"country": "GB", "archetype": "STORE", "sites": 10,
          "density": "URBAN"}],
        promoted=[{"country": "FR", "archetype": "PLANT", "sites": 4,
                   "promoted_at": "now"}])
    fr = [r for r in merged if r["country"] == "FR"]
    assert fr and fr[0]["density"] is None, (
        "a researched pair has no declared band and must not borrow one")
