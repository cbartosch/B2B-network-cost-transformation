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


def _merge(driver, rows, promoted=None, mix=None, industry="RETAIL"):
    """Run the merge with the database stubbed out.

    `select` is stubbed as well as the session: the merge builds a real
    SQLAlchemy select over evidenced_footprint, and a fake table is not a
    FROM clause. The subject here is what the merge does with the rows, not
    how it asks for them.

    Two different queries run against this stub - the promoted footprint
    rows, then one density_mix lookup per row that arrived with no band - so
    sessions are handed out in that order. The band fill opens its own
    session per row, which is what makes the order usable.
    """
    import types

    class _Q:
        def where(self, *a, **k):
            return self

    driver.select = lambda *a, **k: _Q()
    opened = []

    class _Session:
        def __init__(self):
            self._first = not opened
            opened.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            payload = (promoted or []) if self._first else (mix or [])
            return types.SimpleNamespace(
                all=lambda: [types.SimpleNamespace(**p) for p in payload])

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
        evidenced_footprint=types.SimpleNamespace(c=_Cols()),
        density_mix=types.SimpleNamespace(c=_Cols()))
    spec = _spec(rows)
    spec["industry"] = industry
    return driver.footprint_for_simulation("case", spec)


def _mix_row(archetype, band, share, industry="RETAIL"):
    return {"industry": industry, "archetype": archetype,
            "density_band": band, "share": share}


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


def test_a_researched_pair_never_borrows_the_band_beside_it(driver):
    """A researched pair has no band of its own. It may take one from the
    governed sector mix - that is a stated default - but never from whatever
    declared row happens to sit next to it in the same estate, which would
    read as a finding about this client and is about a different site type
    in a different country."""
    merged, _o, _p = _merge(
        driver,
        [{"country": "GB", "archetype": "STORE", "sites": 10,
          "density": "URBAN"}],
        promoted=[{"country": "FR", "archetype": "PLANT", "sites": 4,
                   "promoted_at": "now"}],
        mix=[])            # the mix has no PLANT row, so nothing fills it
    fr = [r for r in merged if r["country"] == "FR"]
    assert fr and all(r["density"] is None for r in fr)


def test_a_researched_pair_takes_its_band_from_the_governed_mix(driver):
    """The fill itself: a counted, typed row with no band is spread across
    the sector's bands rather than left untested. Without this the row
    matches no serviceability key and its sites resolve DELIVERED."""
    merged, _o, prov = _merge(
        driver,
        [{"country": "GB", "archetype": "STORE", "sites": 10,
          "density": "URBAN"}],
        promoted=[{"country": "FR", "archetype": "PLANT", "sites": 100,
                   "promoted_at": "now"}],
        mix=[_mix_row("PLANT", "SUBURBAN", "0.6"),
             _mix_row("PLANT", "RURAL", "0.4")])
    fr = [r for r in merged if r["country"] == "FR"]
    assert {r["density"] for r in fr} == {"SUBURBAN", "RURAL"}
    assert sum(r["sites"] for r in fr) == 100, "the counted total is evidence"
    filled = [p for p in prov if p.get("origin") == "DENSITY_FROM_MIX"]
    assert filled and filled[0]["sites"] == 100
    assert filled[0]["filled"][0]["basis"] == "INDUSTRY_DEFAULT"


def test_a_declared_band_is_not_overwritten_by_the_mix(driver):
    """A declared band is a statement about this client and outranks a
    sector norm, however confident the norm is."""
    merged, _o, prov = _merge(
        driver,
        [{"country": "GB", "archetype": "STORE", "sites": 10,
          "density": "URBAN"}],
        mix=[_mix_row("STORE", "RURAL", "1.0")])
    assert [r["density"] for r in merged] == ["URBAN"]
    assert not [p for p in prov if p.get("origin") == "DENSITY_FROM_MIX"]
