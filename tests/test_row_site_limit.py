"""How many sites one footprint row may carry.

An analyst was told "the run is refused above 100 per row" about rows of 2,280
to 11,400 that had breached the 2,000 cluster ceiling, and advised to "split
them by site type" - which is unfollowable, because every row reaching this
check has already chosen one.

Two defects in one message: it reported a limit it had not applied, and its
remedy named a dimension already used.

A third defect underneath: one ceiling for every archetype refused estates it
should have accepted. A packstation network genuinely is 20,000 near-identical
sites - same product, same bandwidth, same posture - and forcing it into ten
rows of 2,000 adds no information. The homogeneity claim is weakest exactly
where the counts are largest.
"""
import types
from pathlib import Path


def _rule():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "footprint.py").read_text()
    namespace = {}
    exec(source[source.index("UNIFORM_ARCHETYPES = frozenset"):], namespace)
    return namespace


POLICY = types.SimpleNamespace(max_sites_per_archetype_row=100,
                               max_sites_per_cluster_row=2000,
                               max_sites_per_uniform_row=25000)


def test_a_mass_deployed_cluster_gets_the_higher_ceiling():
    """20,000 packstations in one row is a fair claim. They are deployed to
    one specification."""
    rule = _rule()
    for archetype in ("STORE", "NETWORK_SITE"):
        limit, _why = rule["row_site_limit"](
            {"archetype": archetype, "density": "URBAN"}, POLICY)
        assert limit == 25000, archetype


def test_an_individually_significant_site_does_not():
    """11,400 German offices in one row is a claim nobody made."""
    rule = _rule()
    for archetype in ("LARGE_OFFICE", "DC", "PLANT", "CAMPUS", "TERMINAL"):
        limit, _why = rule["row_site_limit"](
            {"archetype": archetype, "density": "URBAN"}, POLICY)
        assert limit == 2000, archetype


def test_a_row_with_no_density_band_gets_the_lowest_ceiling():
    """It asserts a whole country's estate is alike, which claims the most."""
    rule = _rule()
    limit, _why = rule["row_site_limit"]({"archetype": "STORE"}, POLICY)
    assert limit == 100


def test_the_limit_comes_back_with_the_reason_it_was_chosen():
    """So the message can name the limit it applied. Returning the number
    alone is how the wrong one came to be reported."""
    rule = _rule()
    for row in ({"archetype": "STORE", "density": "URBAN"},
                {"archetype": "DC", "density": "URBAN"},
                {"archetype": "STORE"}):
        limit, why = rule["row_site_limit"](row, POLICY)
        assert isinstance(limit, int) and why and isinstance(why, str)


def test_the_remedy_never_names_a_dimension_already_used():
    """"Split by site type" was the old advice, and the site type is chosen
    before this check can fire."""
    rule = _rule()
    remedy = rule["row_limit_remedy"](
        {"archetype": "LARGE_OFFICE", "density": "URBAN"})
    assert "split by density or country" in remedy.lower()

    # a row with no band still has one free dimension, and that is the advice
    remedy = rule["row_limit_remedy"]({"archetype": "STORE"})
    assert "density band" in remedy


def test_both_layers_use_the_one_rule():
    """The page and the API reported different numbers. Reporting a limit
    other than the one enforced is the defect, not the limit itself."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "footprint_resolver.row_site_limit(" in api
    assert "footprint_resolver.row_limit_remedy(" in api

    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/5_Simulation*.py")).read_text()
    assert "_row_limit(r)[0]" in page, "the page must report what it applied"
    assert "max_sites_per_uniform_row" in page


def test_the_third_ceiling_is_published_to_the_interface():
    """A literal copy in the page meant a steward retuning the governed value
    got an interface that disagreed with the API."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert 'resolved["max_sites_per_uniform_row"]' in api
