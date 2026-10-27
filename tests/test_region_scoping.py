"""Scoping a case by region reaches every country the card can price.

REGION resolved from a hand list written before the system had an atlas:
EMEA was GB, DE, FR, NL and AE, APAC was Singapore and the Americas the US.
The rate card prices every country `reference.country_region` places - at its
own rate, or at its sub-region's or that sub-region's parent's median - so
choosing EMEA scoped a case to five of the 125 EMEA countries it could price,
and GLOBAL stopped at the 78 with a card of their own.

Pre-flight and the research brief made the same mistake from the other side:
they counted a country's own rows, so a country priced at its region's median
was reported as having no price at all.
"""
import types
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert

from app import db
from app.domain import preflight, research, scope

ATLAS = {"ES": "EUROPE_SOUTH", "AD": "EUROPE_SOUTH", "ET": "AFRICA_SSA",
         "SG": "APAC", "BD": "APAC", "US": "AMER", "BO": "AMER"}


def _price(session, where, kind="COUNTRY"):
    session.execute(insert(db.unit_cost_prior).values(
        id=f"{where}-DIA-100", country=where, scope_kind=kind, product="DIA",
        cost_layer="L0", bandwidth_mbps=100, low=80, base=100, high=120,
        currency="USD", price_year=2026, approved=True, evidence_grade="E",
        price_basis="SEED"))


@pytest.fixture()
def card(session):
    """ES, SG, US and ZZ priced on their own; Southern Europe, EMEA and APAC
    priced as regions. AFRICA_SSA has no rate, so Ethiopia falls to EMEA;
    AMER has none and no parent, so Bolivia prices nowhere. ZZ has a card
    and no place in the atlas; XK has neither."""
    for country, region in ATLAS.items():
        session.execute(insert(db.country_region).values(
            country=country, region=region))
    for country in ("ES", "SG", "US", "ZZ"):
        _price(session, country)
    for region in ("EUROPE_SOUTH", "EMEA", "APAC"):
        _price(session, region, kind="REGION")
    session.commit()
    return session


def test_each_country_is_priced_at_the_first_rung_of_its_ladder(card):
    assert scope.pricing_scopes(card, ["ES", "AD", "ET", "BO", "XK"]) == {
        "ES": "ES", "AD": "EUROPE_SOUTH", "ET": "EMEA", "BO": None,
        "XK": None}


@pytest.mark.parametrize("region,members", [
    ("EMEA", ["AD", "ES", "ET"]),
    ("APAC", ["BD", "SG"]),
    # Bolivia is in the atlas and nothing on its ladder prices it.
    ("AMERICAS", ["US"]),
])
def test_a_region_reaches_every_country_in_it_the_card_can_price(
        card, region, members):
    countries, chosen = scope.resolve(card, scope_mode="REGION",
                                      region=region, explicit_countries=None)
    assert (countries, chosen) == (members, region)


def test_global_reaches_regional_prices_and_never_names_a_region(card):
    countries, chosen = scope.resolve(card, scope_mode="GLOBAL", region=None,
                                      explicit_countries=None)
    assert chosen == "GLOBAL"
    assert countries == ["AD", "BD", "ES", "ET", "SG", "US", "ZZ"]


def test_an_unknown_region_is_refused(card):
    with pytest.raises(ValueError, match="EUROPE"):
        scope.resolve(card, scope_mode="REGION", region="EUROPE",
                      explicit_countries=None)


def test_the_route_lists_each_regions_members(card, monkeypatch):
    from app.routers import api
    monkeypatch.setattr(api, "S", lambda: card)
    monkeypatch.setattr(card, "close", lambda: None)
    out = api.list_regions()
    assert out["regions"] == ["AMERICAS", "APAC", "EMEA"]
    assert out["members"]["EMEA"] == ["AD", "ES", "ET"]


def _case(session, countries):
    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Holdings PLC",
        entity_identifier="5493001KJTIIGC8Y1R12", country_of_domicile="ES",
        group_perimeter="SINGLE_ENTITY", in_scope_countries=countries,
        in_scope_cost_layers=["L0"], in_scope_service_families=["WAN"],
        base_currency="USD", price_year=2026, fx_convention="BUDGET",
        analysis_horizon_years=5, discount_rate_set_id="DRS-2026-USD",
        engagement_purpose="PROPOSAL_QUALIFICATION",
        client_contact_status="NO_CONTACT", baseline_reference_period="FY2026",
        resolved_entity_id="cand-1", entity_confirmed_by="Priya Raman",
        entity_confirmed_at=datetime.now(timezone.utc), perimeter_version=1))
    session.commit()
    return case_id


def _coverage(report):
    return next(c for c in report["conditions"]
                if c["item"] == "Prior coverage")


def test_preflight_counts_a_regional_price_as_coverage(card):
    report = preflight.run(card, case_id=_case(card, ["ES", "AD", "ET"]),
                           mode="DETERMINISTIC_ONLY")
    condition = _coverage(report)
    assert condition["state"] == "PASS", condition
    assert "2 of them only at a regional median" in condition["detail"]


def test_preflight_still_warns_where_no_rung_prices(card):
    report = preflight.run(card, case_id=_case(card, ["ES", "BO"]),
                           mode="DETERMINISTIC_ONLY")
    condition = _coverage(report)
    assert condition["state"] == "WARN"
    assert "BO" in condition["detail"] and "ES" not in condition["detail"]


def test_the_price_brief_does_not_call_a_regionally_priced_country_unpriced(
        card):
    row = types.SimpleNamespace(case_id="case-1",
                                in_scope_countries=["ES", "AD", "BO"])
    state = research._build_context(card, row, 19)["model_state"]
    assert "ES DIA @ 100 Mbps" in state
    assert "priced at their region's median: AD." in state
    assert "NO approved price at all: BO." in state


def test_the_serviceability_brief_names_only_what_cannot_be_priced(card):
    row = types.SimpleNamespace(case_id="case-1",
                                in_scope_countries=["ES", "AD", "BO"])
    state = research._build_context(card, row, 18)["model_state"]
    assert "currently unpriceable: BO." in state
    assert "Priced only at their region's median: AD." in state


def test_a_scope_saved_before_the_atlas_is_re_resolved_once(card):
    """Four Global cases saved in September kept the 78-country list Global
    meant then, until somebody saved their intake again. Migration v71
    resolves them as saving would - and leaves an explicit list alone."""
    from sqlalchemy import select, update

    from app import migrations

    stale = _case(card, ["ES", "SG", "US"])
    chosen = _case(card, ["ES"])
    card.execute(update(db.case).where(db.case.c.case_id == stale)
                 .values(in_scope_region="GLOBAL"))
    card.commit()

    migrations._migrate_v71(card.connection())
    card.commit()

    scopes = dict(card.execute(select(
        db.case.c.case_id, db.case.c.in_scope_countries)).all())
    assert scopes[stale] == ["AD", "BD", "ES", "ET", "SG", "US", "ZZ"]
    assert scopes[chosen] == ["ES"]
