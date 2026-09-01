"""The three-tier topology the simulation generates.

Every site used to get an access circuit to a notional in-country POP and
nothing else. That is not a WAN, it is a set of unconnected local loops - so
the baseline understated itself and no backbone-consolidation lever had
anything to act on.

  ACCESS          site to in-country POP, product and bandwidth per archetype
  DC_TO_REGION    data centre to its regional hub
  REGION_TO_CORE  regional hub to the global core

Head offices are access tier by design: a large office is a big local
connection, not a core node, and treating one as a hub would put a backbone
circuit wherever an entity happens to have a headquarters.
"""
import json

import pytest

from app.domain import topology

TEMPLATE = {"version": "1.0.0", "dc_to_region_product": "ETHERNET",
            "dc_to_region_mbps": 10000, "region_to_core_product": "ETHERNET",
            "region_to_core_mbps": 10000, "dc_dual": True, "core_dual": True}
REGIONS = {"DE": "EMEA", "GB": "EMEA", "FR": "EMEA", "NL": "EMEA",
           "AE": "EMEA", "US": "AMER", "SG": "APAC"}


def _plan(footprint):
    return topology.plan(footprint, regions=REGIONS, template=TEMPLATE)


def test_data_centres_cluster_into_regions_and_regions_into_a_core():
    plan = _plan([
        {"country": "DE", "archetype": "STORE", "sites": 350},
        {"country": "DE", "archetype": "DC", "sites": 2},
        {"country": "US", "archetype": "DC", "sites": 1},
        {"country": "SG", "archetype": "DC", "sites": 1}])

    tiers = {link["tier"] for link in plan["links"]}
    assert tiers == {topology.DC_TO_REGION, topology.REGION_TO_CORE}
    assert plan["hub_regions"] == ["AMER", "APAC", "EMEA"]
    # 4 DCs + 3 hubs to the core, each dual.
    assert plan["backbone_circuits"] == (4 + 3) * 2


def test_a_head_office_is_access_tier_not_a_hub():
    """A large office is a big local connection. Treating one as a core node
    would put a backbone circuit wherever an entity has a headquarters."""
    plan = _plan([{"country": "DE", "archetype": "LARGE_OFFICE", "sites": 8},
                  {"country": "GB", "archetype": "LARGE_OFFICE", "sites": 3}])
    assert plan["links"] == []
    assert "no data centres" in plan["note"]
    assert "LARGE_OFFICE" not in topology.HUB_ARCHETYPES


def test_one_region_gets_no_core_tier():
    """A hub has nothing to reach across, and a core link from one hub to
    itself is not a circuit."""
    plan = _plan([{"country": "DE", "archetype": "STORE", "sites": 341},
                  {"country": "DE", "archetype": "DC", "sites": 1}])
    assert {link["tier"] for link in plan["links"]} == {topology.DC_TO_REGION}
    assert "no global core tier" in plan["note"]


def test_an_estate_with_no_data_centre_gets_no_backbone():
    """Correct for a footprint of leaves, and stated as correct rather than
    left looking like a gap in the model."""
    plan = _plan([{"country": "DE", "archetype": "STORE", "sites": 341}])
    assert plan["backbone_circuits"] == 0
    assert "not a gap in the model" in plan["note"]


def test_an_unmapped_country_is_reported_and_never_guessed():
    """Giving it a region silently would put a backbone link to a hub nobody
    chose into the estimate."""
    plan = _plan([{"country": "JP", "archetype": "DC", "sites": 2},
                  {"country": "DE", "archetype": "DC", "sites": 1}])
    assert plan["unmapped_countries"] == ["JP"]
    assert "JP" in plan["note"]
    # The Japanese data centres contribute no backbone at all.
    assert sum(link["count"] for link in plan["links"]
               if link["tier"] == topology.DC_TO_REGION) == 1


def test_the_plan_is_deterministic():
    """It carries no seeded draw, so it must not move the simulated share or
    the output hash between identical runs."""
    footprint = [{"country": "DE", "archetype": "DC", "sites": 2},
                 {"country": "US", "archetype": "DC", "sites": 1}]
    first, second = _plan(footprint), _plan(list(reversed(footprint)))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_backbone_edges_match_the_access_edge_shape():
    """So the pricing path, the coverage count and the sample table treat a
    core circuit as the circuit it is."""
    plan = _plan([{"country": "DE", "archetype": "DC", "sites": 1},
                  {"country": "US", "archetype": "DC", "sites": 1}])
    for edge in topology.edges(plan):
        assert set(edge) >= {"from", "to", "product", "role",
                             "bandwidth_mbps", "diversity_state", "tier"}
        assert edge["diversity_state"] == "SIMULATED", (
            "simulated structure can never claim to be evidenced (0.3B)")
    json.dumps(topology.edges(plan))


def test_every_backbone_product_and_tier_is_priceable():
    """Without a prior for the region the backbone lands unpriced, and adding a
    core would have dragged coverage down - a change that made the estimate
    worse while looking more complete."""
    from app.seed import PRIORS
    tiers = {(c, p, bw) for c, p, _l, bw, *_ in PRIORS}
    for region in ("EMEA", "AMER", "APAC"):
        assert (region, TEMPLATE["dc_to_region_product"],
                TEMPLATE["dc_to_region_mbps"]) in tiers, region


def test_the_simulation_version_moved_with_the_shape():
    """Adding a core changes the output hash for the same seed and footprint."""
    from app import config
    major, minor = config.SIMULATION_MODEL_VERSION.split("-")[1].split(".")[:2]
    assert (int(major), int(minor)) >= (1, 3)


# ------------------------------------------------- a price may be regional
def test_a_price_scope_may_be_a_region_and_says_so():
    """The first regional backbone row failed to insert: country was an ISO
    alpha-2 field and I put "EMEA" in it.

    Widening the column alone would have left country = 'EMEA', which is false
    data that reads as a fact - so scope_kind records which it is instead of
    leaving the kind to be inferred from the length of a string."""
    from app import db
    columns = {c.name: c for c in db.unit_cost_prior.columns}
    assert "scope_kind" in columns
    assert columns["country"].type.length >= 16, (
        "a region code does not fit in an ISO alpha-2 field")


def test_the_seed_labels_regional_rows_as_regions():
    from app.seed import COUNTRY_REGION, PRIORS, REGION_CODES
    assert REGION_CODES == sorted({r for _c, r in COUNTRY_REGION}), (
        "the region codes a price may use must come from the region table, or "
        "a backbone price can be scoped to a region nobody maps to")
    regional = [c for c, *_ in PRIORS if c in REGION_CODES]
    assert set(regional) == set(REGION_CODES), (
        "every region needs a backbone price or its core circuits are unpriced")


def test_a_region_is_never_offered_as_an_in_scope_country():
    """GLOBAL resolves from distinct prior scopes. Offering "EMEA" there would
    put a region into a country list, where every downstream consumer treats it
    as an ISO code."""
    import inspect
    from app.domain import scope
    src = inspect.getsource(scope)
    assert 'scope_kind != "REGION"' in src


def test_the_estimate_loads_the_regions_its_countries_map_into():
    """The prior filter was the case's country list alone, so every backbone
    circuit would have landed unpriced - a change that makes the estimate worse
    while looking more complete. And only the regions the case actually reaches:
    a case with no APAC sites has no business pricing an APAC backbone."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers" / "api.py").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "in_scope_regions" in api
    assert "(countries or [\"--\"]) + in_scope_regions" in api
