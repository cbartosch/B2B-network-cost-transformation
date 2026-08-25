"""End-to-end flow through the real HTTP API.

Every other test in this suite checks one component. This one checks that they
compose: that the gates fire in the right order, that each refusal names its
cause, and that a stage cannot be reached by skipping the work in front of it.
That is a different failure class - each part can be correct while the chain
between them is not.

The flow deliberately runs with **no provider configured**, which is the state
a fresh checkout is in. That is not a limitation of the test; it is the most
important case, because it proves the system refuses rather than inventing
output when it cannot reach a model.

Written after driving the API end to end by hand and finding two defects that
no unit test had surfaced. It exists so the next such defect is caught here.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app import db
from app.domain import dispositions, questionnaire
from app.main import app

BASE = "/v1/outside-in/cases"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _intake(client) -> str:
    r = client.post(BASE, json={
        "created_by": "Jane Okafor",
        "subject_entity_legal_name": "Acme Global Logistics",
        "country_of_domicile": "GB",
        "in_scope_countries": ["GB", "DE"],
        "engagement_ref": "ENG-FLOW-1"})
    assert r.status_code == 200, r.json()
    return r.json()["case_id"]


def _confirm_entity_directly(case_id: str) -> None:
    """Entity resolution needs a provider. With none configured it fails closed,
    which `test_entity_resolution_fails_closed_without_a_provider` asserts. The
    rest of the flow still has to be reachable, so the confirmation is written
    directly here - the same state a real resolution would leave behind."""
    with db.SessionLocal() as s:
        s.execute(update(db.case).where(db.case.c.case_id == case_id).values(
            resolved_entity_id="LEI-FLOW-0001",
            entity_confirmed_by="Jane Okafor",
            entity_confirmed_at=datetime.now(timezone.utc)))
        s.commit()


def _dispose_all(client, case_id, disposition="BENCHMARK_PRIOR"):
    return client.put(f"{BASE}/{case_id}/domain-dispositions", json=[
        {"domain_no": n, "domain_name": nm, "disposition": disposition}
        for n, nm in dispositions.DOMAINS])


# --------------------------------------------------------------- the chain

def test_intake_then_read_back_round_trips(client):
    case_id = _intake(client)
    r = client.get(f"{BASE}/{case_id}")
    assert r.status_code == 200
    assert r.json()["subject_entity_legal_name"] == "Acme Global Logistics"


def test_entity_resolution_fails_closed_without_a_provider(client):
    """The single most important behaviour in the bundle: no provider means no
    output, not fabricated output."""
    case_id = _intake(client)
    r = client.post(f"{BASE}/{case_id}/entities:resolve",
                    json={"name_hint": "Acme Global Logistics"})
    assert r.status_code == 503, r.json()
    detail = str(r.json()).lower()
    assert "not configured" in detail and "fails" in detail


def test_simulation_is_refused_while_preflight_blocks(client):
    """0.1C gates execution. A blocked pre-flight must stop the simulation, and
    the refusal must name which conditions are open rather than failing
    generically."""
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    r = client.post(f"{BASE}/{case_id}/simulations:run", json={
        "seed": 42, "ensemble_size": 5,
        "footprint": [{"country": "GB", "archetype": "LARGE_OFFICE", "sites": 40}]})
    # There are two distinct correct refusals here, and the flow audit found
    # the second only by running it:
    #   * no pre-flight report has been produced at all (0.1C must run first)
    #   * a report exists and carries open BLOCK conditions
    # Both stop the simulation, and the message names which. What must never
    # happen is the simulation running while pre-flight is unsatisfied.
    assert r.status_code in (202, 409), r.json()
    if r.status_code == 409:
        detail = str(r.json()).lower()
        assert "pre-flight" in detail or "block" in detail, r.json()
    else:
        pf = client.post(f"{BASE}/{case_id}/preflight:run", json={}).json()
        assert not [c for c in pf["conditions"] if c["state"] == "BLOCK"], (
            "the simulation was accepted while pre-flight had open blocks")


def test_preflight_reports_its_conditions_and_can_be_acknowledged(client):
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    r = client.post(f"{BASE}/{case_id}/preflight:run", json={})
    assert r.status_code == 200, r.json()
    report = r.json()
    assert report["conditions"], "a report with no conditions proves nothing"
    ack = client.post(f"{BASE}/{case_id}/preflight:acknowledge",
                      json={"report_id": report["report_id"],
                            "acknowledged_by": "Jane Okafor"})
    assert ack.status_code == 200, ack.json()


def test_known_facts_round_trip_with_attribution(client):
    case_id = _intake(client)
    r = client.post(f"{BASE}/{case_id}/known-facts", json={
        "fact_class": "SITE_COUNT", "subject": "global estate",
        "value_base": 120, "unit": "count", "asserted_by": "Jane Okafor",
        "assertion_date": "2026-05-01", "basis": "CLIENT_CONVERSATION",
        "verifiability": "CLIENT_CONFIRMABLE"})
    assert r.status_code == 200, r.json()
    facts = client.get(f"{BASE}/{case_id}/known-facts").json()
    assert facts, "the fact just written must read back"


def test_an_unattributed_known_fact_is_rejected(client):
    case_id = _intake(client)
    r = client.post(f"{BASE}/{case_id}/known-facts", json={
        "fact_class": "SITE_COUNT", "subject": "global estate", "value_base": 1,
        "asserted_by": "", "assertion_date": "2026-05-01",
        "basis": "CLIENT_CONVERSATION", "verifiability": "CLIENT_CONFIRMABLE"})
    assert r.status_code in (400, 422), r.json()


def test_dispositions_round_trip_all_24_domains(client):
    case_id = _intake(client)
    r = _dispose_all(client, case_id)
    assert r.status_code == 200, r.json()
    assert r.json()["stored"] == len(dispositions.DOMAINS)
    assert r.json()["publication_blockers"] == []


# --------------------------------------------------------------- Tranche 3 chain

def test_the_v1_gate_blocks_without_an_estimate(client):
    """The gate must refuse on the work that is genuinely missing, and say so."""
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    _dispose_all(client, case_id)
    r = client.post(f"{BASE}/{case_id}/stage:assess", json={"target_stage": "V1"})
    assert r.status_code == 200, r.json()
    report = r.json()
    assert report["blocked"] is True
    assert "V0 estimate" in {b["item"] for b in report["blocks"]}


def test_advancing_a_blocked_case_is_refused(client):
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    client.post(f"{BASE}/{case_id}/stage:assess", json={"target_stage": "V1"})
    r = client.post(f"{BASE}/{case_id}/stage:advance",
                    json={"target_stage": "V1", "advanced_by": "Sam Patel"})
    assert r.status_code == 409, r.json()


def test_questionnaire_prefill_map_and_gate_compose(client):
    """Tranche 3 end to end: create, prefill without a provider, answer, map
    onto the disposition contract, and see the mapping reflected in the gate."""
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    _dispose_all(client, case_id)

    assert client.post(f"{BASE}/{case_id}/questionnaire").status_code == 200
    pre = client.post(f"{BASE}/{case_id}/questionnaire:prefill",
                      json={"mode": "DETERMINISTIC_ONLY"})
    assert pre.status_code == 200, pre.json()
    assert pre.json()["failed"] == 0, "the deterministic path needs no provider"

    for key, _, _ in questionnaire.QUESTIONS:
        a = client.post(f"{BASE}/{case_id}/questionnaire:answer", json={
            "question_key": key, "answer_value": "an answer",
            "answered_by": "Client Contact"})
        assert a.status_code == 200, a.json()

    loaded = client.get(f"{BASE}/{case_id}/questionnaire").json()
    assert loaded["complete"] is True

    mapped = client.post(f"{BASE}/{case_id}/questionnaire:map",
                         json={"mapped_by": "Jane Okafor"})
    assert mapped.status_code == 200, mapped.json()
    assert mapped.json()["upgraded"] == len(questionnaire.QUESTIONS)

    disp = client.get(f"{BASE}/{case_id}/domain-dispositions").json()
    by_domain = {d["domain_no"]: d["disposition"] for d in disp["dispositions"]}
    for _, _, domain_no in questionnaire.QUESTIONS:
        assert by_domain[domain_no] == "CLIENT_CONFIRMED", (
            "an answered question must reach the disposition contract")

    report = client.post(f"{BASE}/{case_id}/stage:assess",
                         json={"target_stage": "V1"}).json()
    open_items = {b["item"] for b in report["blocks"]}
    assert "V1 questionnaire" not in open_items
    assert "Answer mapping" not in open_items


def test_a_client_answer_does_not_overwrite_public_evidence_through_the_api(client):
    case_id = _intake(client)
    _confirm_entity_directly(case_id)
    _dispose_all(client, case_id, disposition="EVIDENCED_PUBLIC")
    client.post(f"{BASE}/{case_id}/questionnaire")
    for key, _, _ in questionnaire.QUESTIONS:
        client.post(f"{BASE}/{case_id}/questionnaire:answer", json={
            "question_key": key, "answer_value": "an answer",
            "answered_by": "Client Contact"})
    mapped = client.post(f"{BASE}/{case_id}/questionnaire:map",
                         json={"mapped_by": "Jane Okafor"}).json()
    assert mapped["upgraded"] == 0
    assert mapped["requiring_adjudication"] == len(questionnaire.QUESTIONS)

    disp = client.get(f"{BASE}/{case_id}/domain-dispositions").json()
    assert all(d["disposition"] == "EVIDENCED_PUBLIC" for d in disp["dispositions"])


# --------------------------------------------------------------- always-available

def test_the_operational_endpoints_answer_without_a_case(client):
    for path in ("/v1/health", "/v1/ready", "/v1/agents",
                 "/v1/integrity/attestation", "/v1/integrity/incidents"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_health_reports_the_running_build_not_a_stale_constant(client):
    from app import _version
    assert client.get("/v1/health").json()["build"] == _version.BUILD


def test_an_unknown_route_is_a_404_not_a_500(client):
    assert client.get("/v1/definitely-not-a-route").status_code == 404


def test_preflight_guidance_covers_every_condition(client):
    """The interface maps each pre-flight condition to the page that clears it.
    A key that does not match a real condition name renders nothing, silently -
    two of the first eight were invented from memory and matched nothing. This
    pins the mapping to what the service actually emits."""
    import pathlib
    import re

    page = (pathlib.Path(__file__).resolve().parents[1]
            / "analyst_ui" / "streamlit_app" / "pages" / "3_Pre_flight.py").read_text()
    mapped = set(re.findall(r'^    "([^"]+)":', page, re.M))

    case_id = _intake(client)
    report = client.post(f"{BASE}/{case_id}/preflight:run", json={}).json()
    real = {c["item"] for c in report["conditions"]}

    assert not (mapped - real), (
        f"the interface offers guidance for conditions that do not exist: "
        f"{sorted(mapped - real)}")
    assert not (real - mapped), (
        f"these conditions can block a run with no guidance on how to clear "
        f"them: {sorted(real - mapped)}")


def test_a_preflight_report_says_which_case_it_belongs_to(client):
    """Without this the interface cannot tell a cached report from another
    case's, and Streamlit session state outlives a case switch."""
    case_id = _intake(client)
    posted = client.post(f"{BASE}/{case_id}/preflight:run", json={}).json()
    assert posted["case_id"] == case_id
    fetched = client.get(f"{BASE}/{case_id}/preflight").json()
    assert fetched["case_id"] == case_id


def test_reading_a_preflight_report_never_creates_one(client):
    """A GET that created a report would silently supersede an acknowledgement."""
    case_id = _intake(client)
    assert client.get(f"{BASE}/{case_id}/preflight").status_code == 404
    client.post(f"{BASE}/{case_id}/preflight:run", json={})
    first = client.get(f"{BASE}/{case_id}/preflight").json()["report_id"]
    assert client.get(f"{BASE}/{case_id}/preflight").json()["report_id"] == first
