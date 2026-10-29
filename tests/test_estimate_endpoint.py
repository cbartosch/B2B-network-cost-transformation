"""estimates:run, driven over HTTP through the real route.

Three defects reached the browser through this one endpoint, and every one of
them lived in the seam between a route and the code it calls rather than in
either side:

  * `build_components()` was called with `footprint_origin=` and
    `users_origin=`, which it does not accept. Every request raised TypeError
    before a single line of calculation ran, from the original build onward.
    The unit tests call `build_components` directly with the right keywords,
    so the calculation was well covered and the route was never exercised.
  * a simulation stored before the bandwidth dimension has product rows with
    no bandwidth, so nothing could be priced and the coverage gate refused at
    0% - a true refusal naming the wrong problem.
  * the ANCHOR path returned the snapshot's shape rather than the response's,
    so the interface raised KeyError the moment an anchor run succeeded.

Unit tests on both sides of a broken seam pass happily. These drive the whole
path - app, middleware, route, domain, database - and assert the contract the
interface actually reads.

The setup is deliberately explicit rather than fixtured behind a helper: a
case only reaches this endpoint after entity confirmation, an acknowledged
pre-flight report and a complete 24-domain disposition contract, and writing
that out is a readable statement of what V0 requires.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select

from app import db
from app.domain.money import D
from app.domain import dispositions
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _ready_case(session, *, countries=("GB",), base_currency="USD",
                layers=("L0",)) -> str:
    """A case in the one state estimates:run will accept.

    Seeds reference data explicitly. The `session` fixture drops and recreates
    the schema and the TestClient lifespan seeds it, so which of the two runs
    first decides whether the governed policies exist - a hidden coupling that
    would make these pass or fail on fixture ordering rather than on the code
    under test.
    """
    from app.seed import seed
    seed(force=False)

    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics",
        entity_identifier="5493001KJTIIGC8Y1R12", country_of_domicile="GB",
        group_perimeter="SINGLE_ENTITY", in_scope_countries=list(countries),
        in_scope_cost_layers=list(layers), in_scope_service_families=["WAN"],
        base_currency=base_currency, price_year=2026, fx_convention="BUDGET",
        analysis_horizon_years=5, discount_rate_set_id="DRS-2026-USD",
        engagement_purpose="PROPOSAL_QUALIFICATION",
        client_contact_status="NO_CONTACT", baseline_reference_period="FY2026",
        resolved_entity_id="cand-1", entity_confirmed_by="Priya Raman",
        entity_confirmed_at=datetime.now(timezone.utc), perimeter_version=1))

    # 0.1C: a run may not begin without a cleared, acknowledged report.
    session.execute(insert(db.preflight_report).values(
        report_id=str(uuid.uuid4()), case_id=case_id, conditions=[],
        blocked=False, acknowledged_by="Priya Raman",
        acknowledged_at=datetime.now(timezone.utc)))

    # 0.3A: every one of the 24 domains carries a disposition, or V0 cannot
    # publish. BENCHMARK_PRIOR needs no reason; DECLARED_UNKNOWN would.
    for no, name in dispositions.DOMAINS:
        session.execute(insert(db.domain_disposition).values(
            id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
            domain_no=no, domain_name=name, disposition="BENCHMARK_PRIOR",
            reason=None, agent_run_id=None, evidence=None))
    session.commit()
    return case_id


def _simulation(session, case_id, *, with_bandwidth=True, country="GB") -> str:
    """A completed simulation. with_bandwidth=False reproduces a run stored
    before 4.53.0, which is the state that priced nothing."""
    sim_id = str(uuid.uuid4())
    row = {"country": country, "product": "DIA", "role": "PRIMARY", "count": 100}
    if with_bandwidth:
        row["bandwidth_mbps"] = 100
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=sim_id, case_id=case_id,
        model_version="sim-1.1.0" if with_bandwidth else "sim-1.0.0",
        seed=42, ensemble_size=1, params={"footprint": []},
        output={"sites": 100, "circuits": 100, "products": [row]},
        output_hash="deadbeef", status="SUCCEEDED",
        progress_completed=1, progress_total=1))
    session.commit()
    return sim_id


def _prior(session, *, country="GB", product="DIA", mbps=100,
           low=380, base=520, high=720):
    # Pinned, not merely inserted. reference.unit_cost_prior is seeded now
    # (1,308 rows), so a bare insert collided on the primary key and every
    # test using this helper errored in setup. Skipping the insert instead
    # would be worse: the estimate would be computed from whatever the seed
    # holds, and these tests assert on 380/520/720.
    prior_id = f"{country}-{product}-{mbps}"
    session.execute(delete(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == prior_id))
    session.execute(insert(db.unit_cost_prior).values(
        id=prior_id, country=country, product=product,
        cost_layer="L0", bandwidth_mbps=mbps, low=low, base=base, high=high,
        currency="USD", price_year=2026, approved=True))
    session.commit()


# --------------------------------------------------------------- the contract
RESPONSE_KEYS = {"estimate_snapshot_id", "v0_status", "current_tco", "by_layer",
                 "scenarios", "confidence", "coverage", "simulated_share",
                 "asserted_share"}


def test_build_up_runs_end_to_end_and_returns_the_contract(session, client):
    """The test that would have caught the TypeError. It asserts nothing about
    the size of the answer - only that the route reaches a calculation and
    hands back what the interface reads."""
    case_id = _ready_case(session)
    sim_id = _simulation(session, case_id)
    _prior(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})

    assert r.status_code == 200, r.text
    body = r.json()
    assert RESPONSE_KEYS <= set(body), sorted(RESPONSE_KEYS - set(body))
    # The interface reads this exact path; a by-layer dict here raises KeyError.
    assert "base" in body["current_tco"]
    assert float(body["current_tco"]["base"]) > 0, (
        "a priced circuit produced no value - the calculation ran but priced "
        "nothing")


def test_anchor_runs_end_to_end_and_returns_the_same_contract(session, client):
    """The test that would have caught the KeyError. Same assertions, so the
    two methods cannot drift into different shapes."""
    case_id = _ready_case(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000,
                          "users": 500, "ops_cost_per_site_base": 900})

    assert r.status_code == 200, r.text
    body = r.json()
    assert RESPONSE_KEYS <= set(body), sorted(RESPONSE_KEYS - set(body))
    assert "base" in body["current_tco"]
    assert body["method"] == "ANCHOR"
    basis = body["anchor_basis"]
    assert float(basis["addressable_pool"]["base"]) < 213_000_000, (
        "the pool must be a share of the anchor, not the anchor itself")


def test_every_scenario_carries_what_it_costs_to_get_there(session, client):
    """The wiring, which is the part that was missing.

    transition.net, TransitionPolicy, the page 8 renderer and
    validation_capture's one-time-cost extraction were all written and all
    correct. Nothing built a policy and passed it to scenarios(), so
    estimate.py's `if transition_policy is not None` was never true and every
    scenario ever published reported a gross run-rate saving with no payback
    and no one-time cost - the exact defect the module was written for: "P3:
    none of this existed, so every scenario reported a gross saving as though
    it were the answer."

    Nothing failed while that was true. The domain tests passed, because they
    call transition.net directly; the endpoint tests passed, because none of
    them looked for the block. This asserts at the seam the two met at.
    """
    case_id = _ready_case(session)
    sim_id = _simulation(session, case_id)
    _prior(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})
    assert r.status_code == 200, r.text
    scenarios = r.json()["scenarios"]
    assert scenarios, "no scenarios to check"

    for code, scenario in scenarios.items():
        transition = scenario.get("transition")
        assert transition, (
            f"scenario {code} reports a saving with no cost of getting there")
        # The figures a business case turns on, each a band.
        for field in ("one_time_cost", "dual_running_cost",
                      "total_transition_cost"):
            assert set(transition[field]) >= {"low", "base", "high"}
        assert set(transition["payback_months"]) == {
            "optimistic", "base", "pessimistic"}
        assert transition["programme_months"] >= 1
        # Says what it is. A modelled payback presented as a business case is
        # worse than no payback.
        assert "modelled payback" in transition["payback_basis"]

    # And it survives being stored: the scenarios go into a JSON column, which
    # is where a stray Decimal last took out this route.
    stored = session.execute(select(db.estimate_snapshot.c.scenarios).where(
        db.estimate_snapshot.c.estimate_snapshot_id
        == r.json()["estimate_snapshot_id"])).scalar()
    assert all(s.get("transition") for s in stored.values())


def test_the_transition_is_costed_for_the_estate_that_was_simulated(session,
                                                                    client):
    """Not for some other number of sites.

    site_count() reads the estate back from the components rather than taking
    it as an argument, so this checks the two agree. A site count that is
    wrong in either direction is silent - it produces a plausible payback,
    not an error - and the one-time cost is linear in it.
    """
    case_id = _ready_case(session)
    sim_id = _simulation(session, case_id)
    _prior(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})
    assert r.status_code == 200, r.text
    body = r.json()

    # _simulation() publishes output {"sites": 100, ...}, so the estate the
    # estimate priced is 100 sites and the transition has to be costed for
    # 100 - not for the circuit count, which is also 100 here only by
    # coincidence of the fixture, and not for twice that, which is what a
    # flat sum over every site-driven layer would give.
    sites = 100

    transition = next(iter(body["scenarios"].values()))["transition"]
    # The seeded band is 400 / 900 / 1800 per site.
    assert D(transition["one_time_cost"]["base"]) == D(900) * sites
    assert D(transition["one_time_cost"]["low"]) == D(400) * sites
    assert D(transition["one_time_cost"]["high"]) == D(1800) * sites
    # ceil(100 / 120 sites a month) = 1
    assert transition["programme_months"] == 1


def test_a_recommendation_carries_the_payback_of_the_scenario_it_names(
        session, client):
    """Page 8 renders this and has been showing its fallback instead.

    The block is read from the snapshot rather than stored on the
    recommendation row: it belongs to (snapshot, scenario_code), which the
    recommendation already names, so a copy would be free to drift.
    """
    case_id = _ready_case(session)
    sim_id = _simulation(session, case_id)
    _prior(session)
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})
    assert r.status_code == 200, r.text
    snapshot_id = r.json()["estimate_snapshot_id"]
    code = sorted(r.json()["scenarios"])[0]

    rec_id = str(uuid.uuid4())
    session.execute(insert(db.recommendation).values(
        recommendation_id=rec_id, estimate_snapshot_id=snapshot_id,
        case_id=case_id, scenario_code=code, percentile="base",
        basis="t", label="DETERMINISTIC_PROPOSED",
        gross_run_rate_savings={"base": "1"}, material_levers=[]))
    session.commit()

    listed = client.get(f"/v1/outside-in/cases/{case_id}/recommendations")
    assert listed.status_code == 200, listed.text
    found = [x for x in listed.json()["recommendations"]
             if x["recommendation_id"] == rec_id]
    assert found and found[0].get("transition"), (
        "the recommendation names a scenario whose payback is known, and the "
        "page that renders it was told there was none")

    one = client.get(
        f"/v1/outside-in/cases/{case_id}/recommendations/{rec_id}")
    assert one.status_code == 200, one.text
    assert one.json()["transition"] == found[0]["transition"]


def test_a_simulation_without_bandwidth_is_refused_by_name(session, client):
    """The test that would have caught the third one. Before this the run
    priced nothing and reported 0% coverage, which is true and names the wrong
    problem: the evidence was fine, the stored run was stale."""
    case_id = _ready_case(session)
    sim_id = _simulation(session, case_id, with_bandwidth=False)
    _prior(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "simulation predates the bandwidth dimension"
    assert "Re-run the simulation" in detail["detail"], (
        "a refusal that does not name the remedy sends the reader to the "
        "coverage gate instead")


def test_build_up_without_a_simulation_says_so(session, client):
    """A method that prices an enumerated estate needs one. Silently falling
    back to ANCHOR would produce a number whose basis nobody chose."""
    case_id = _ready_case(session)

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "users": 500,
                          "ops_cost_per_site_base": 900})

    assert r.status_code == 422, r.text
    assert "BUILD_UP requires a simulation" in str(r.json()["detail"])


def test_anchor_without_an_anchor_says_so(session, client):
    case_id = _ready_case(session)
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "users": 500,
                          "ops_cost_per_site_base": 900})
    assert r.status_code == 422, r.text
    assert "anchor_value" in str(r.json()["detail"])


def test_an_unknown_method_is_refused_rather_than_defaulted(session, client):
    """Defaulting a typo to BUILD_UP would run a method the caller did not ask
    for and report it as if they had."""
    case_id = _ready_case(session)
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCOHR", "anchor_value": 1000})
    assert r.status_code == 422, r.text
    assert "ANCHOR" in str(r.json()["detail"])


def test_an_undisposed_domain_blocks_publication(session, client):
    """0.3A is a completeness contract. Removing one disposition must stop the
    run, not shrink the denominator."""
    case_id = _ready_case(session)
    session.execute(db.domain_disposition.delete().where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 7))
    session.commit()

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000})

    assert r.status_code == 409, r.text
    assert "V0 cannot publish" in str(r.json()["detail"])


def test_an_unacknowledged_preflight_stops_the_run(session, client):
    """0.1C: a BLOCK condition or an unacknowledged report prevents execution.
    This is the gate the whole ordering rests on."""
    case_id = _ready_case(session)
    session.execute(db.preflight_report.update()
                    .where(db.preflight_report.c.case_id == case_id)
                    .values(acknowledged_by=None, acknowledged_at=None))
    session.commit()

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000})

    assert r.status_code == 409, r.text
    assert "acknowledg" in str(r.json()["detail"]).lower()


def test_a_snapshot_is_persisted_and_readable(session, client):
    """The estimate is a record, not just a response. A run that answers and
    stores nothing leaves the deck renderer and the audit trail with nothing
    to read."""
    case_id = _ready_case(session)
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000})
    assert r.status_code == 200, r.text
    snap_id = r.json()["estimate_snapshot_id"]

    listed = client.get(f"/v1/outside-in/cases/{case_id}/estimates")
    assert listed.status_code == 200
    ids = [s["estimate_snapshot_id"] for s in listed.json()["snapshots"]]
    assert snap_id in ids
    stored = next(s for s in listed.json()["snapshots"]
                  if s["estimate_snapshot_id"] == snap_id)
    assert stored["pins"]["estimate_method"] == "ANCHOR", (
        "which method produced a stored estimate has to survive in the record")


# --------------------------------------------------------------- simulation scope
def test_a_footprint_of_all_zeros_is_refused_by_name(session, client):
    """Zeroing every row is now a deliberate act - the editor opens on one
    site per in-scope country - but it must still refuse. Unguarded it
    simulates nothing successfully and the failure surfaces two pages later as
    "no priced components": a true statement about an empty estate that reads
    as a pricing problem."""
    case_id = _ready_case(session, countries=("GB", "DE", "US"))

    r = client.post(f"/v1/outside-in/cases/{case_id}/simulations:run",
                    json={"seed": 42, "ensemble_size": 1,
                          "footprint": [
                              {"country": "GB", "archetype": "BRANCH", "sites": 0},
                              {"country": "DE", "archetype": "BRANCH", "sites": 0},
                              {"country": "US", "archetype": "BRANCH", "sites": 0}]})

    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "footprint has no sites"
    assert "promote" in detail["detail"], (
        "the refusal should name the route to evidence, not just the mistake")


def test_a_single_row_carrying_a_whole_estate_is_disclosed(session, client):
    """A bulk row is priced and the assumption is disclosed, not refused.

    A row asserts that every site in it shares one bandwidth, one primary and
    backup product and one dual-access probability, and the whole row is
    costed at that archetype's tier, so a bulk total in one row puts a claim
    into the baseline that nobody stated out loud.

    This used to be a 422 at 100 sites, and it was withdrawn deliberately -
    "it made it unusable on the estates that most need it, and the analyst's
    only route through was to mis-type the rows". It was replaced by pricing
    the row and pinning what was assumed: homogeneity_report's own basis line
    says "nothing is refused for this - the row prices and the claim is
    disclosed".

    So the old premise is gone twice over. The limit is not 100 and there is
    no limit: rows are reported above a band of 2,000 (25,000 where the
    archetype is mass-deployed to one specification and a density is given).
    This exercises 3,000 un-banded STORE sites, which is above the band it is
    actually judged against.

    The share is the point. One row means something different at 3% of an
    estate than at 100% of it, so what is pinned is the share, not the
    count."""
    case_id = _ready_case(session, countries=("DE",))

    r = client.post(f"/v1/outside-in/cases/{case_id}/simulations:run",
                    json={"seed": 42, "ensemble_size": 1,
                          "footprint": [{"country": "DE",
                                         "archetype": "STORE",
                                         "sites": 3000}]})

    assert r.status_code == 202, r.text
    run_id = r.json()["simulation_run_id"]

    params = session.execute(select(db.simulation_run.c.params).where(
        db.simulation_run.c.simulation_run_id == run_id)).scalar()
    hom = params["homogeneity"]
    assert hom["sites_in_large_rows"] == 3000
    assert hom["share_in_large_rows"] == "1.000", (
        "the whole estate is priced as one block; a reader has to be able to "
        "see that from the pinned run")
    assert hom["share_asserted_alike"] == "1.000", (
        "with no density band the row is not uniform by construction - it is "
        "an assertion the analyst made, not a property of the archetype")
    assert any(row["archetype"] == "STORE" for row in hom["rows"])


def test_an_allocated_footprint_of_the_same_total_is_accepted(session, client):
    """The remedy has to work: the same estate, split by site type, runs."""
    case_id = _ready_case(session, countries=("DE",))
    _prior(session)

    rows = ([{"country": "DE", "archetype": "STORE", "sites": 100}] * 8
            + [{"country": "DE", "archetype": "WAREHOUSE", "sites": 90},
               {"country": "DE", "archetype": "LARGE_OFFICE", "sites": 8},
               {"country": "DE", "archetype": "DC", "sites": 2}])
    r = client.post(f"/v1/outside-in/cases/{case_id}/simulations:run",
                    json={"seed": 42, "ensemble_size": 1, "footprint": rows})
    assert r.status_code in (200, 202), r.text


def test_anchor_does_not_require_a_driver_it_never_uses(session, client):
    """ANCHOR derives its OPS layer as a governed share of the addressable
    pool and never multiplies a per-site rate - anchor_estimate.py does not
    mention ops at all.

    Making the figure mandatory for every method therefore refused a valid
    request for a driver the calculation would not have used. Two existing
    tests caught it on the first real run."""
    case_id = _ready_case(session, countries=("DE",))

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000})
    assert r.status_code != 422 or "no ops cost per site" not in r.text, (
        "ANCHOR must not be refused for a BUILD_UP driver")


def test_build_up_still_refuses_a_missing_ops_cost(session, client):
    """The refusal exists because 900 per site used to be a server-side
    default that reached the baseline whenever a caller omitted the field."""
    case_id = _ready_case(session, countries=("DE",))

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "users": 500})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no ops cost per site"


def test_a_prior_is_resolved_by_scope_specificity():
    """Openreach publishes by regulated area and by distance from the serving
    exchange. A less specific scope is consulted only when the more specific
    one has nothing at all - not when it has a worse price, because a national
    average is not a better answer than a local tariff."""
    from app.domain.estimate import match_prior

    priors = {("GB", "MPLS", 100): {"base": "980"},
              ("Area 2", "MPLS", 100): {"base": "760"},
              ("CASE-x", "MPLS", 100): {"base": "308"}}

    assert match_prior(priors, "GB", "MPLS", 100)[0]["base"] == "980"
    assert match_prior(priors, "GB", "MPLS", 100,
                       scopes=["Area 2", "GB"])[0]["base"] == "760"
    assert match_prior(priors, "GB", "MPLS", 100,
                       scopes=["CASE-x", "Area 2", "GB"])[0]["base"] == "308"
    # a scope with no price falls through rather than failing
    assert match_prior(priors, "GB", "MPLS", 100,
                       scopes=["Area 9", "GB"])[0]["base"] == "980"


def test_a_country_without_a_rate_prices_at_its_region(session, client):
    """The regional rungs were loaded and never consulted.

    Since EMEA split, this route has loaded each country's sub-region and its
    parent into `priors`, and nothing passed the chain to `match_prior` - so
    E.ON's Hungarian, Czech, Romanian and Swedish 5G backups were unpriced
    beside the Central European and EMEA rates that would have priced them.
    Every test of the fallback called `match_prior` with the chain written out
    by hand, which is the one thing the route never did.

    Hungary falls one rung, to EUROPE_CENTRAL. Sweden's band has no 5G rate,
    so it falls two, to EMEA. Germany has its own and keeps it - at 300 Mbps,
    the tier Telekom's business 5G is sold at. (Romania was the two-rung case
    until Orange Romania's business 5G gave it a rate of its own.)
    """
    countries = ("DE", "HU", "SE")
    case_id = _ready_case(session, countries=countries)
    sim_id = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=sim_id, case_id=case_id, model_version="sim-1.1.0",
        seed=42, ensemble_size=1, params={"footprint": []},
        output={"sites": 30, "circuits": 30, "products": [
            {"country": c, "product": "MOBILE_5G", "role": "BACKUP",
             "count": 10, "bandwidth_mbps": 100,
             "service_class": "BEST_EFFORT", "access_technology": "MOBILE_5G"}
            for c in countries]},
        output_hash="deadbeef", status="SUCCEEDED",
        progress_completed=1, progress_total=1))
    session.commit()

    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage"]["unpriced_pairs"] == []
    assert body["coverage"]["regionally_priced_pairs"] == [
        "HU/MOBILE_5G at EUROPE_CENTRAL", "SE/MOBILE_5G at EMEA"]
    assert sorted(c["key"] for c in body["components"]
                  if c["layer"] == "L0") == [
        "L0_backup_DE_MOBILE_5G_100M_priced_at_300M",
        "L0_backup_HU_MOBILE_5G_100M_priced_at_300M_priced_in_EUROPE_CENTRAL",
        "L0_backup_SE_MOBILE_5G_100M_priced_at_150M_priced_in_EMEA"]


def test_the_platform_layers_convert_into_the_case_currency(session, client):
    """The platform card is priced in USD and was the one rate set the route
    never converted, so a EUR case paid the overlay's USD 55 a site a month
    as EUR 55 - and a JPY case as JPY 55, which put Toyota's platform layers
    at EUR 3,008. The same estate priced in EUR must cost its USD price at
    the factor every access rate uses."""
    from app.domain import currency

    def by_layer(base_currency):
        case_id = _ready_case(session, base_currency=base_currency,
                              layers=("L0", "L2", "L4"))
        sim_id = _simulation(session, case_id)
        _prior(session)
        r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                        json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                              "users": 500, "ops_cost_per_site_base": 900})
        assert r.status_code == 200, r.text
        return r.json()["by_layer"]

    usd, eur = by_layer("USD"), by_layer("EUR")
    factor = currency.rate_table(
        [{"from_currency": r.from_currency, "to_currency": r.to_currency,
          "rate": r.rate, "as_of": str(r.as_of) if r.as_of else None,
          "convention": r.convention, "source": r.source,
          "evidence_grade": r.evidence_grade}
         for r in session.execute(select(db.fx_rate)).all()],
        currencies=["USD"], to="EUR", convention="BUDGET",
        as_of="2026-12-31")["factors"]["USD"]
    assert factor != 1
    for layer in ("L2", "L4"):
        assert D(usd[layer]["base"]) > 0, layer
        expected = D(usd[layer]["base"]) * factor
        assert abs(D(eur[layer]["base"]) - expected) < D("0.01"), (
            f"{layer}: EUR {eur[layer]['base']}, expected {expected:.2f} - "
            f"USD {usd[layer]['base']} converted at {factor}")


def test_per_site_costs_stated_in_usd_convert_into_the_case_currency(
        session, client):
    """The operations cost and the one-time cost per site are USD figures
    that were read as each case's own, so the same 900 was 900 euros for
    Iberdrola and 900 yen for Toyota. Stated in USD, both convert at the
    factor every rate uses. An ops cost stated with no currency is still the
    case's own, as the request has always meant."""
    from app.domain import currency

    def run(base_currency, ops_currency=None):
        case_id = _ready_case(session, base_currency=base_currency,
                              layers=("L0", "OPS"))
        sim_id = _simulation(session, case_id)
        _prior(session)
        body = {"method": "BUILD_UP", "simulation_run_id": sim_id,
                "users": 500, "ops_cost_per_site_base": 900}
        if ops_currency:
            body["ops_cost_per_site_currency"] = ops_currency
        r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                        json=body)
        assert r.status_code == 200, r.text
        return r.json()

    usd, eur, eur_own = run("USD", "USD"), run("EUR", "USD"), run("EUR")
    factor = currency.rate_table(
        [{"from_currency": r.from_currency, "to_currency": r.to_currency,
          "rate": r.rate, "as_of": str(r.as_of) if r.as_of else None,
          "convention": r.convention, "source": r.source,
          "evidence_grade": r.evidence_grade}
         for r in session.execute(select(db.fx_rate)).all()],
        currencies=["USD"], to="EUR", convention="BUDGET",
        as_of="2026-12-31")["factors"]["USD"]
    assert factor != 1

    def close(got, expected):
        return abs(D(got) - D(expected)) < D("0.01")

    assert close(eur["by_layer"]["OPS"]["base"],
                 D(usd["by_layer"]["OPS"]["base"]) * factor)
    assert eur_own["by_layer"]["OPS"]["base"] == usd["by_layer"]["OPS"]["base"]
    with_transition = [k for k, sc in usd["scenarios"].items()
                       if "transition" in sc]
    assert with_transition
    for k in with_transition:
        usd_cost = usd["scenarios"][k]["transition"]["one_time_cost"]["base"]
        eur_cost = eur["scenarios"][k]["transition"]["one_time_cost"]["base"]
        assert close(eur_cost, D(usd_cost) * factor), (
            f"scenario {k}: EUR {eur_cost}, expected USD {usd_cost} "
            f"converted at {factor}")


def test_the_ops_floor_is_judged_after_conversion(session, client):
    """900 stated in JPY is about USD 6 a site a year. Checked before
    conversion it passed the floor that catches a monthly figure, and priced
    a USD case's operations at almost nothing."""
    case_id = _ready_case(session, layers=("L0", "OPS"))
    sim_id = _simulation(session, case_id)
    _prior(session)
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "BUILD_UP", "simulation_run_id": sim_id,
                          "users": 500, "ops_cost_per_site_base": 900,
                          "ops_cost_per_site_currency": "JPY"})
    assert r.status_code == 422, r.text
    detail = str(r.json())
    assert "JPY" in detail and "USD" in detail, detail


def test_an_anchor_estimate_pins_the_rate_its_one_time_cost_converted_at(
        session, client):
    """ANCHOR converts the one-time cost per site as BUILD_UP does, and pins
    the rate as BUILD_UP does, so an FX row changing cannot move a payback
    with nothing recorded to say why."""
    case_id = _ready_case(session, base_currency="EUR")
    r = client.post(f"/v1/outside-in/cases/{case_id}/estimates:run",
                    json={"method": "ANCHOR", "anchor_value": 213_000_000,
                          "users": 500, "ops_cost_per_site_base": 900})
    assert r.status_code == 200, r.text
    pins = session.execute(select(db.estimate_snapshot.c.pins).where(
        db.estimate_snapshot.c.estimate_snapshot_id
        == r.json()["estimate_snapshot_id"])).scalar()
    assert pins["fx"]["to"] == "EUR"
    assert "USD" in pins["fx"]["rates"]
