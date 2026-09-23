"""What to research, for the estate this industry actually has.

A brief was one text per domain, the same for every client. So an agent
researching a bank was never asked for the standalone cash machine count, and
one researching a parcel network was never asked how many packstations there
are - while those are the largest rows in their respective estates.

The asks are DERIVED from the industry's estate shape. A hand-maintained list
of 49 industries would be stale the week after it was written, which is the
defect this repository has found in a hardcoded list four times.
"""
from collections import defaultdict
from pathlib import Path

from app.domain import bics, industry_asks


def _estate(industry):
    from app.seed import DENSITY_MIX

    mix = defaultdict(set)
    for code, archetype, _band, _share in DENSITY_MIX:
        mix[code].add(archetype)
    return mix[industry]


def _asks(industry):
    return [a["archetype"] for a in industry_asks.asks_for(
        _estate(industry), industry=industry,
        shape=bics.shape_for(industry))]


def test_the_data_centre_count_is_always_asked():
    """It drives cost more than any other single site and cannot be derived
    from a share of the estate."""
    for industry in ("RETAIL_BANKING", "CHEMICALS", "TOWER_COMPANY",
                     "POSTAL_AND_PARCEL_NETWORK", "SOFTWARE"):
        assert _asks(industry)[0] == "DC", industry


def test_the_data_centre_count_is_required_before_publishing():
    for industry in ("RETAIL_BANKING", "CHEMICALS", "SUPERMARKETS"):
        required = industry_asks.required_counts(
            _estate(industry), shape=bics.shape_for(industry))
        assert "DC" in required, industry


def test_a_bank_is_asked_for_standalone_cash_machines():
    """The estate shape proposes none by design, so an unresearched count
    stays zero. Asking is the only way the number ever exists."""
    assert "ATM" in _asks("RETAIL_BANKING")
    required = industry_asks.required_counts(
        _estate("RETAIL_BANKING"), shape="branch-network")
    assert "ATM" in required


def test_a_chemicals_company_is_not_asked_about_cash_machines():
    """A brief full of irrelevant questions is one an agent learns to skim.

    Keyed on the estate shape rather than on BRANCH, which is a bank branch
    in one estate and a small non-customer-facing site in every other."""
    assert "ATM" not in _asks("CHEMICALS")
    assert "ATM" not in industry_asks.required_counts(
        _estate("CHEMICALS"), shape="plant-centric")


def test_a_parcel_network_is_asked_for_its_own_site_types():
    asks = _asks("POSTAL_AND_PARCEL_NETWORK")
    assert "SELF_SERVICE_TERMINAL" in asks
    assert "SERVICE_POINT" in asks
    assert "TERMINAL" in asks


def test_every_asked_type_says_where_to_look():
    """An ask without a source is a question, not a brief."""
    for industry in ("RETAIL_BANKING", "POSTAL_AND_PARCEL_NETWORK"):
        for ask in industry_asks.asks_for(
                _estate(industry), industry=industry,
                shape=bics.shape_for(industry)):
            assert ask["look_for"], ask["archetype"]
            assert ask["why"], ask["archetype"]


def test_every_site_type_in_any_shape_has_an_ask():
    """A type an estate can contain and nobody is asked about is a count the
    model will invent."""
    from app.domain import industries

    in_shapes = {a for rows in industries.SHAPES.values()
                 for a, _b, _s in rows}
    missing = sorted(in_shapes - set(industry_asks.SITE_TYPE_ASKS))
    assert not missing, missing


def test_the_asks_reach_the_endpoint_and_the_page():
    """Computed and dropped is the defect this session found five times."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"site_count_asks": _asks' in api
    assert '"required_counts": _required' in api

    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/4_Domain_disposition*.py")).read_text()
    assert "site_count_asks" in page
    assert "needed before V0" in page
