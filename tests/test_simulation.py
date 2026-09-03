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
