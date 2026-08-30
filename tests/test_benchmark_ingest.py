"""Benchmark ingestion: getting a benchmark in, and what must not happen on the way.

Before this the vault schema was declared and empty and every benchmark was a
constant in seed.py written approved=True. These cover the two rules the design
rests on: an agent interprets but never calculates, and prior-engagement
material contributes to nothing until someone clears it by name.
"""
import uuid

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import benchmark_ingest as bi


def _obs(session, **over):
    row = dict(observation_id=str(uuid.uuid4()), source_document="rfp.pptx",
               rights_basis="PUBLISHED", rights_cleared=True, metric="MRC",
               country="US", product="DIA", bandwidth_mbps=100,
               vendor="AT&T", value=477, unit="USD/month", currency="USD")
    row.update(over)
    session.execute(insert(db.benchmark_observation).values(**row))
    session.commit()
    return row["observation_id"]


def test_a_band_is_the_observed_spread_of_cleared_quotes(session):
    """Seven vendor quotes for one country/product/bandwidth become one band.
    min/median/max, not a fitted distribution: with seven points the observed
    spread is the range a buyer faces, and fitting would dress the same
    information up as more."""
    for v, vendor in [(367, "Brightspeed"), (442, "Fusion"), (460, "Comcast"),
                      (477, "AT&T"), (523, "CommandLink"), (531, "Lumen"),
                      (609, "Verizon")]:
        _obs(session, value=v, vendor=vendor)

    out = bi.derive_bands(session, dry_run=True)
    band = out["derived"][0]
    assert (band["low"], band["base"], band["high"]) == (367, 477, 609)
    assert band["observations"] == 7 and len(band["vendors"]) == 7


def test_prior_engagement_material_contributes_to_nothing_until_cleared(session):
    """Another client's negotiated pricing is not a benchmark. Same rule
    known_facts applies to a PRIOR_ENGAGEMENT fact, for the same reason (2.4)."""
    for v in (367, 442, 460):
        _obs(session, value=v, rights_basis="PRIOR_ENGAGEMENT",
             rights_cleared=False)

    out = bi.derive_bands(session, dry_run=True)
    assert out["derived"] == []
    assert len(out["skipped"]) == 3
    assert all("rights" in s["reason"] for s in out["skipped"])


def test_clearing_rights_requires_a_named_person(session):
    oid = _obs(session, rights_basis="PRIOR_ENGAGEMENT", rights_cleared=False)
    with pytest.raises(ValueError):
        bi.clear_rights(session, observation_ids=[oid], cleared_by="")


def test_a_foreign_currency_is_skipped_rather_than_converted(session):
    """An FX rate is a governed input with a date and a source. Converting
    inside a derivation would put an unattributable number into a priced
    band - the exact thing the agent is forbidden to do, done by code."""
    for v in (400, 420, 440):
        _obs(session, value=v, currency="EUR")
    out = bi.derive_bands(session, currency="USD", dry_run=True)
    assert out["derived"] == []
    assert all("currency" in s["reason"] for s in out["skipped"])


def test_an_observation_missing_a_pricing_dimension_is_reported_not_guessed(session):
    """A quote with no bandwidth cannot be matched by the estimate lookup.
    Null is visible; a typical value substituted for it is not."""
    for v in (367, 442, 460):
        _obs(session, value=v, bandwidth_mbps=None)
    out = bi.derive_bands(session, dry_run=True)
    assert out["derived"] == []
    assert all("bandwidth_mbps" in s["reason"] for s in out["skipped"])


def test_too_few_observations_makes_no_band(session):
    """A low/high from two quotes states a spread the evidence cannot support."""
    _obs(session, value=367)
    _obs(session, value=609)
    out = bi.derive_bands(session, min_observations=3, dry_run=True)
    assert out["derived"] == [] and len(out["too_few_observations"]) == 1


def test_a_derived_band_is_written_unapproved_with_its_observations(session):
    for v in (367, 477, 609):
        _obs(session, value=v)
    bi.derive_bands(session, dry_run=False)
    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == "US-DIA-100-derived")).one()
    assert row.approved is False
    assert row.bandwidth_mbps == 100
    assert "observation_ids" in row.source_note


def test_hfc_and_pon_never_merge_into_one_band(session):
    """The split only means something if the derivation keeps them apart."""
    for v in (132, 166, 268):
        _obs(session, product="BROADBAND_HFC", value=v)
    for v in (80, 120, 200):
        _obs(session, product="BROADBAND_PON", value=v)
    out = bi.derive_bands(session, dry_run=True)
    products = {d["product"] for d in out["derived"]}
    assert products == {"BROADBAND_HFC", "BROADBAND_PON"}
