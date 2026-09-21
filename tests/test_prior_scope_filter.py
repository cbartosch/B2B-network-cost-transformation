"""Which countries the estimate loads rates for.

A GB footprint came back with 4,120 circuits, 0 priced and coverage 0.0% - on
a rate card that held GB DIA 100 Mbps at $335, the exact row the scope
reported as unpriced.

The scope being priced comes from the simulated footprint. The rate query was
filtered by the case's declared in_scope_countries. Two lists, and nothing
forcing them to agree: a footprint row in a country the case never declared
loaded no rates for it.

The comment in the route records the same defect found once before and fixed
only on the region half - a backbone circuit is scoped to EMEA and the filter
named only countries. The country half stayed, and the gap widened as
footprint rows became easier to create anywhere: 242 countries now reach a
region and 78 have their own card.
"""
from pathlib import Path


def _route():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    return (app / "routers" / "api.py").read_text()


def test_the_filter_covers_the_simulated_scope_not_just_the_declared_list():
    route = _route()
    assert "_simulated = sorted({" in route, (
        "the countries in the simulated footprint must be loaded")
    assert "countries = sorted(set(_declared) | set(_simulated))" in route


def test_it_is_a_union_so_it_can_only_add_rates():
    """A case whose declared list already covers its footprint must be
    unaffected. A filter change that could remove a rate would trade one
    silent under-pricing for another."""
    route = _route()
    assert "set(_declared) | set(_simulated)" in route
    assert "countries = case_row.in_scope_countries or []" not in route


def test_it_reads_the_same_structure_coverage_prices_from():
    """If the union read a different shape than derive_scope iterates, it
    would load rates for the wrong countries and look correct."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    coverage = (app / "domain" / "coverage.py").read_text()
    route = _route()

    assert 'sim_output.get("products", [])' in coverage
    assert '(sim.output or {}).get(\n                "products", [])' in route \
        or '"products", []' in route


def test_the_regions_are_still_loaded_alongside():
    """A backbone circuit is priced against EMEA. The region half of this
    filter was the earlier fix and must survive the country half."""
    route = _route()
    assert "in_scope_regions" in route
    assert "countries or [\"--\"]) + in_scope_regions" in route


def test_a_missing_country_is_still_visible_rather_than_defaulted():
    """Loading more rates must not turn an unpriceable circuit into a priced
    one at an invented rate. A country with no card still falls through the
    scope ladder and, failing that, stays unpriced."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    coverage = (app / "domain" / "coverage.py").read_text()
    assert '"priced": prior is not None' in coverage
