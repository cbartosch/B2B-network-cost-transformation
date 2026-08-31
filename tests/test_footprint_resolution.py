"""Where the footprint comes from.

This rule lived in the simulation page as four branches of Streamlit logic and
was wrong in a different way on four separate occasions: it ignored the case's
own scope, then it discarded typed counts on rerun, then it persisted only what
had been run, then it never read the known-facts register at all. Each fix was
correct and none was the last, because the rule was expressed in the one place
that could not be tested.
"""
import uuid

import pytest
from sqlalchemy import insert

from app import db
from app.domain import footprint


def _case(session, **over):
    case_id = str(uuid.uuid4())
    values = dict(case_id=case_id, created_by="t",
                  subject_entity_legal_name="Adolf Wuerth GmbH & Co. KG",
                  country_of_domicile="DE",
                  in_scope_countries=["DE", "FR", "GB", "US", "NL", "SG", "AE"])
    values.update(over)
    session.execute(insert(db.case).values(**values))
    session.commit()
    return case_id


def _fact(session, case_id, value, *, subject="Adolf Wuerth GmbH & Co. KG",
          state="PENDING", fact_class="Location footprint"):
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class=fact_class, subject=subject, value_base=value, unit="sites",
        asserted_by="CB", basis="THIRD_PARTY_REPORT",
        verifiability="PUBLICLY_VERIFIABLE", corroboration_state=state))
    session.commit()


def test_a_registered_fact_reaches_the_footprint_without_being_applied(session):
    """The failure reported four times: a fact sat in the register while the
    simulation ran on placeholders, because applying it meant finding a panel
    and clicking through it."""
    case_id = _case(session)
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT"
    assert out["footprint"] == [{"country": "DE", "archetype": "BRANCH",
                                 "sites": 1000}]
    assert out["needs_split"] is True


def test_the_total_is_not_spread_across_countries(session):
    """A fact says how many sites there are, not where. Splitting 1000 evenly
    across seven in-scope countries would invent six numbers."""
    case_id = _case(session)
    _fact(session, case_id, 1000)
    out = footprint.resolve(session, case_id)
    assert len(out["footprint"]) == 1
    assert "not a breakdown" in out["split_note"]


def test_a_corroborated_fact_beats_an_uncorroborated_one(session):
    case_id = _case(session)
    _fact(session, case_id, 500, subject="Wuerth", state="UNCORROBORATED")
    _fact(session, case_id, 2900, state="CORROBORATED")
    out = footprint.resolve(session, case_id)
    assert out["footprint"][0]["sites"] == 2900
    assert "not used" in out["detail"], (
        "the competing count must be reported, not silently dropped")


def test_a_contradicted_fact_loses_to_a_pending_one(session):
    case_id = _case(session)
    _fact(session, case_id, 9999, state="CONTRADICTED")
    _fact(session, case_id, 1000, state="PENDING")
    assert footprint.resolve(session, case_id)["footprint"][0]["sites"] == 1000


def test_a_saved_footprint_outranks_the_register(session):
    """What a person deliberately saved beats a derivation from a total."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350}])
    _fact(session, case_id, 1000)
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "ANALYST_SAVED"
    assert out["footprint"][0]["sites"] == 350


def test_promoted_research_outranks_everything(session):
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350}])
    _fact(session, case_id, 1000)
    session.execute(insert(db.evidenced_footprint).values(
        id=str(uuid.uuid4()), case_id=case_id, country="DE",
        archetype="STORE", sites=371, source_count=3, band_low=341,
        band_high=400, promoted_by="Priya Raman"))
    session.commit()
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "PROMOTED_RESEARCH"
    assert out["footprint"][0]["sites"] == 371


def test_a_fact_of_another_class_is_not_a_footprint(session):
    case_id = _case(session)
    _fact(session, case_id, 5000, fact_class="Remote-user population")
    assert footprint.resolve(session, case_id)["origin"] == "SCOPE_PLACEHOLDER"


def test_a_case_with_scope_and_nothing_else_is_still_runnable(session):
    case_id = _case(session)
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "SCOPE_PLACEHOLDER"
    assert len(out["footprint"]) == 7
    assert all(r["sites"] == 1 for r in out["footprint"])


def test_a_case_with_no_scope_falls_back_to_illustrative(session):
    case_id = _case(session, in_scope_countries=[], country_of_domicile=None)
    assert footprint.resolve(session, case_id)["origin"] == "ILLUSTRATIVE"


def test_a_valueless_fact_is_ignored(session):
    case_id = _case(session)
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class="Location footprint", subject="Wuerth", value_base=None,
        unit="sites", asserted_by="CB", basis="INDUSTRY_KNOWLEDGE",
        verifiability="PUBLICLY_VERIFIABLE"))
    session.commit()
    assert footprint.resolve(session, case_id)["origin"] == "SCOPE_PLACEHOLDER"


def test_a_saved_placeholder_does_not_outrank_the_register(session):
    """Two of my own changes combined into this.

    Running a simulation persists the footprint, so an edit is not lost on the
    rerun that follows - which meant running the placeholder saved the
    placeholder. That saved placeholder then outranked a registered fact of
    1000 sites, because a saved footprint is normally a decision. The
    convenience of one change became the blocker for another.

    A save that exactly matches what the placeholder would produce records
    nothing anybody decided, so it is treated as absent."""
    case_id = _case(session, analyst_footprint=[
        {"country": c, "archetype": "BRANCH", "sites": 1}
        for c in ["DE", "FR", "GB", "US", "NL", "SG", "AE"]])
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT"
    assert out["footprint"][0]["sites"] == 1000


def test_a_deliberate_single_site_footprint_still_wins(session):
    """The placeholder rule has to be narrow. One site in one country that an
    analyst meant is not the placeholder - it does not match the country set -
    and must not be discarded as though it were."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "BRANCH", "sites": 1}])
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "ANALYST_SAVED"
    assert out["footprint"][0]["sites"] == 1


def test_a_real_saved_footprint_still_outranks_the_register(session):
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350},
        {"country": "FR", "archetype": "STORE", "sites": 120}])
    _fact(session, case_id, 1000)
    assert footprint.resolve(session, case_id)["origin"] == "ANALYST_SAVED"


def test_an_edited_placeholder_is_not_a_placeholder(session):
    """Changing one count makes it a decision about that country."""
    rows = [{"country": c, "archetype": "BRANCH", "sites": 1}
            for c in ["DE", "FR", "GB", "US", "NL", "SG", "AE"]]
    rows[0]["sites"] = 900
    case_id = _case(session, analyst_footprint=rows)
    _fact(session, case_id, 1000)
    assert footprint.resolve(session, case_id)["origin"] == "ANALYST_SAVED"


def test_clearing_the_saved_footprint_falls_back_to_the_register(session):
    case_id = _case(session, analyst_footprint=[])
    _fact(session, case_id, 1000)
    assert footprint.resolve(session, case_id)["origin"] == "KNOWN_FACT"
