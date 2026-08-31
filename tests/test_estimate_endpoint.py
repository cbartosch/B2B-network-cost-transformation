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
from sqlalchemy import insert

from app import db
from app.domain import dispositions
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _ready_case(session, *, countries=("GB",)) -> str:
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
        in_scope_cost_layers=["L0"], in_scope_service_families=["WAN"],
        base_currency="USD", price_year=2026, fx_convention="BUDGET",
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
    session.execute(insert(db.unit_cost_prior).values(
        id=f"{country}-{product}-{mbps}", country=country, product=product,
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
