"""What the ensemble carries out of the passes it runs.

Audit finding C-05: one_pass computed implied_users, bandwidth_profile and
bandwidth_mbps_total on every pass, and aggregate returned none of them - so
the stored output never held them.

The symptom was a route that refused when it should have derived. The estimate
reads implied_users as its fallback headcount when the analyst supplies none;
it was always absent, so the derived branch was unreachable and every request
without a typed headcount was told there was nothing to derive from, while the
simulation had already derived it.
"""
import pytest


# ------------- C-05: values computed per pass and dropped by the aggregate
def _aggregate_of(footprint, archetypes, passes=5):
    from app.domain import simulation
    summaries = [simulation.summarise_pass(
        simulation.one_pass(42 + i, footprint, archetypes), i)
        for i in range(passes)]
    return simulation.aggregate(summaries, seed=42, ensemble_size=passes,
                                footprint=footprint, archetypes=archetypes,
                                model_version="sim-1.6.0")


ARCHETYPES = {
    "STORE": {"dual_access_probability": 0.3,
              "primary_product": "BROADBAND_HFC", "backup_product": "MOBILE_5G",
              "users_base": 12, "bandwidth_mbps_base": 50},
    "LARGE_OFFICE": {"dual_access_probability": 1.0,
                     "primary_product": "ETHERNET", "backup_product": "DIA",
                     "users_base": 250, "bandwidth_mbps_base": 500},
}
FOOTPRINT = [{"country": "GB", "archetype": "STORE", "sites": 1840},
             {"country": "GB", "archetype": "LARGE_OFFICE", "sites": 2}]


def test_the_derived_headcount_survives_aggregation():
    """Audit finding C-05. one_pass computed implied_users and aggregate
    dropped it, so the stored output never held it.

    The estimate reads implied_users as its fallback when the analyst supplies
    no headcount. It was always absent, so the derived branch was unreachable
    and the route refused every time - telling an analyst there was nothing to
    derive from while the simulation had already derived it."""
    out = _aggregate_of(FOOTPRINT, ARCHETYPES)
    assert out["implied_users"] == 1840 * 12 + 2 * 250


def test_the_bandwidth_profile_survives_aggregation():
    out = _aggregate_of(FOOTPRINT, ARCHETYPES)
    assert out["bandwidth_mbps_total"] == 1840 * 50 + 2 * 500
    assert set(out["bandwidth_profile"]) == {"STORE", "LARGE_OFFICE"}


def test_nothing_a_pass_computes_is_silently_dropped():
    """The class, not the instance. Three deterministic values were computed
    every pass and discarded, and the only symptom was a route that refused
    when it should have derived - which reads as a missing input rather than a
    lost one."""
    import ast
    import inspect

    from app.domain import simulation

    tree = ast.parse(inspect.getsource(simulation))

    def returned_keys(name):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        keys = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                keys |= {k.value for k in node.value.keys
                         if isinstance(k, ast.Constant)}
        return keys

    # Carried under another name, deliberately: a per-pass count becomes a
    # percentile band, and the samples become one topology.
    RENAMED = {"dual_sites": "dual_access_sites",
               "circuits_per_site": "circuits_per_site_base",
               "nodes": "sample_topology", "edges": "sample_topology",
               "site_sample": "estate", "estate_full": "estate"}
    lost = sorted(returned_keys("one_pass") - returned_keys("aggregate")
                  - set(RENAMED))
    assert not lost, (
        f"one_pass computes {lost} and aggregate returns neither them nor a "
        f"documented rename")


def test_a_deterministic_value_is_taken_from_the_median_pass_not_averaged():
    """implied_users is fixed by the footprint and the archetype priors, so
    every pass computes the same number. Taking a percentile over identical
    values would imply a spread the model does not have."""
    import inspect

    from app.domain import simulation

    src = inspect.getsource(simulation.aggregate)
    for key in ("implied_users", "bandwidth_profile", "bandwidth_mbps_total"):
        assert f'"{key}": median_pass[' in src, key


# ------------------- C-06: the backbone was modelled and never costed
BACKBONE = {"links": [
    {"tier": "DC_TO_REGION", "region": "EMEA", "count": 2,
     "product": "ETHERNET", "bandwidth_mbps": 10000, "dual": True},
    {"tier": "REGION_TO_CORE", "region": "EMEA", "count": 1,
     "product": "ETHERNET", "bandwidth_mbps": 10000, "dual": True}]}


def _pass(backbone=None):
    from app.domain import simulation
    return simulation.one_pass(
        42, [{"country": "GB", "archetype": "STORE", "sites": 100}],
        {"STORE": {"dual_access_probability": 0.0,
                   "primary_product": "BROADBAND_HFC",
                   "backup_product": "MOBILE_5G", "users_base": 12,
                   "bandwidth_mbps_base": 50}},
        backbone=backbone)


def test_the_backbone_becomes_priceable_circuits():
    """Audit finding C-06. topology.plan() produced the inter-site transport -
    data centres to regional hubs, hubs to a global core - and one_pass
    accepted the parameter and never read it.

    So the backbone was modelled, drawn on the simulation page, and excluded
    from every cost. On a two-data-centre EMEA estate that is 504,000 a year
    absent from the baseline, and absent in the direction that makes a savings
    percentage look larger."""
    without = _pass()
    with_bb = _pass(BACKBONE)
    assert without["circuits_backbone"] == 0
    # 2 DC-to-region and 1 region-to-core link, each dual
    assert with_bb["circuits_backbone"] == 6
    assert with_bb["circuits"] == without["circuits"] + 6


def test_a_backbone_row_is_scoped_to_its_region_not_a_country():
    """A backbone link belongs to no single country, and pricing it against one
    would put a global circuit on whichever market sorted first. The seeded
    priors carry scope_kind=REGION for exactly this."""
    rows = [r for r in _pass(BACKBONE)["products"] if r["role"] == "BACKBONE"]
    assert rows, "the backbone must reach the priced product rows"
    assert all(r["country"] in ("EMEA", "AMER", "APAC") for r in rows)


def test_a_backbone_row_uses_a_role_the_estimate_recognises():
    """The products key is (scope, product, role, bandwidth) and role is
    PRIMARY or BACKUP everywhere else. Putting the tier in that slot would hand
    the estimate a role it has never seen."""
    rows = _pass(BACKBONE)["products"]
    assert {r["role"] for r in rows} <= {"PRIMARY", "BACKUP", "BACKBONE"}


def test_a_backbone_row_prices_against_the_seeded_regional_prior():
    """The circuits are worth nothing if no prior matches them."""
    from app.domain.estimate import match_prior
    from app.seed import PRIORS

    priors = {(r[0], r[1], r[3]): {"low": r[4], "base": r[5], "high": r[6]}
              for r in PRIORS}
    for row in [r for r in _pass(BACKBONE)["products"]
                if r["role"] == "BACKBONE"]:
        prior, _substituted = match_prior(
            priors, row["country"], row["product"], row["bandwidth_mbps"])
        assert prior is not None, (
            f"no regional prior for {row['country']} {row['product']} "
            f"{row['bandwidth_mbps']}M - the backbone would land as unpriced "
            f"scope and drag coverage down")


def test_no_backbone_plan_means_no_backbone_circuits():
    """A single-region estate has nothing to reach across, and the planner
    returns no links. That must cost nothing rather than defaulting."""
    assert _pass({"links": []})["circuits_backbone"] == 0
    assert _pass(None)["circuits_backbone"] == 0
