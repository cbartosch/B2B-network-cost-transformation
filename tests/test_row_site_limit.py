"""How many sites one footprint row may carry: no limit, and a disclosure.

An analyst with a 38,000-site German parcel estate was refused - first with
the wrong limit quoted, then with a remedy naming a dimension already used,
then correctly. The correct refusal was still wrong, because there should not
be a limit at all.

Everything else in this model prices and reports. An expired rate prices and
reports its staleness. A regional fallback prices and records the scope it
used. A substituted bandwidth tier prices and discloses the substitution.
Refusal is reserved for what cannot be computed - a missing rate, a missing
FX pair - not for what can be computed imprecisely.

A large row can be computed. Its homogeneity is a precision caveat exactly
like the others. Refusing a real 24,000-site estate did not make the model
more accurate; it made it unusable on the estates that most need it, and the
analyst's only route through was to mis-type the rows.
"""
from pathlib import Path


def _rule():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "footprint.py").read_text()
    namespace = {}
    exec(source[source.index("UNIFORM_ARCHETYPES = frozenset"):], namespace)
    return namespace


def test_nothing_refuses_a_row_for_its_site_count():
    """The gate is gone from the resolver and from the route."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "carries too many sites" not in api
    assert "row_site_limit" not in api

    footprint = (app / "domain" / "footprint.py").read_text()
    assert "def row_site_limit" not in footprint


def test_a_large_row_is_reported_instead():
    """Priced, and the claim disclosed."""
    rule = _rule()
    note = rule["homogeneity_note"](
        {"country": "DE", "archetype": "LARGE_OFFICE",
         "density": "URBAN", "sites": 11400})
    assert note is not None
    assert note["sites"] == 11400
    assert "strong assumption" in note["note"]
    assert note["narrows_it"]


def test_a_mass_deployed_row_is_unremarkable_until_far_larger():
    """A packstation estate genuinely is 18,000 near-identical sites - same
    product, same bandwidth, same posture."""
    rule = _rule()
    assert rule["homogeneity_note"](
        {"archetype": "STORE", "density": "URBAN", "sites": 18000}) is None
    big = rule["homogeneity_note"](
        {"archetype": "STORE", "density": "URBAN", "sites": 30000})
    assert big is not None and big["uniform_by_construction"] is True


def test_a_small_row_says_nothing():
    """A reporting band, not a gate - and it must stay quiet when there is
    nothing to report."""
    rule = _rule()
    assert rule["homogeneity_note"](
        {"archetype": "LARGE_OFFICE", "density": "URBAN", "sites": 40}) is None


def test_the_report_gives_the_share_not_just_the_count():
    """24,000 sites in one row matters very differently at 3% of the estate
    than at 90% of it."""
    rule = _rule()
    report = rule["homogeneity_report"]([
        {"country": "DE", "archetype": "LARGE_OFFICE", "density": "URBAN",
         "sites": 11400},
        {"country": "DE", "archetype": "STORE", "density": "URBAN",
         "sites": 18000},
        {"country": "GB", "archetype": "STORE", "density": "URBAN",
         "sites": 900},
    ])
    assert len(report["rows"]) == 1, "only the office row is notable"
    assert float(report["share_asserted_alike"]) > 0
    assert float(report["share_in_large_rows"]) > 0


def test_the_report_is_pinned_with_the_run():
    """A computed value nobody reads is the defect this repository keeps
    finding. It belongs with the footprint, because it is part of what the
    number means."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"homogeneity": homogeneity' in api


def test_a_large_share_becomes_a_named_gap():
    """Reported where an analyst reads what the estimate is missing, with the
    act that narrows it."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    qa = (app / "domain" / "estimate_qa.py").read_text()
    assert "estate priced as one block" in qa
    assert "share_asserted_alike" in qa


def test_the_page_no_longer_blocks_the_run():
    root = Path(__file__).resolve().parents[1]
    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/5_Simulation*.py")).read_text()
    assert "disabled=bool(_coarse)" not in page
