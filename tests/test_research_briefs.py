"""Research briefs as governed reference data.

The briefs were a dict in the research module, so retuning the single largest
lever on whether a domain finds anything meant a code change and a rebuild -
and the loop they sit in (read the prompt, run the domain, look at what came
back, adjust the wording) is one an analyst runs, not an engineer.

These cover the move and the two properties that make it safe: production
reads the stored row rather than the module, and a routed domain with no brief
fails closed instead of quietly reverting to the bare-domain-name behaviour
the briefs exist to fix.
"""
import uuid

import pytest
from sqlalchemy import insert, select, update

from app import db
from app.domain import research
from app.domain.research_briefs import BRIEF_CATALOGUE_VERSION, RESEARCH_BRIEFS


def _seeded(session):
    from app.seed import seed
    seed(force=False)
    return session


def test_the_catalogue_covers_every_agent_routed_domain():
    missing = sorted(no for no, agent in research.DOMAIN_AGENT_MAP.items()
                     if agent and no not in RESEARCH_BRIEFS)
    assert not missing, f"routed domains with no brief: {missing}"
    thin = sorted(no for no, b in RESEARCH_BRIEFS.items() if not b.get("search"))
    assert not thin, (
        f"briefs with no search patterns: {thin} - naming the target and "
        f"leaving the agent to invent the query is the old failure in a new "
        f"shape")


def test_the_seed_stores_one_active_brief_per_routed_domain(session):
    _seeded(session)
    rows = session.execute(select(db.research_brief).where(
        db.research_brief.c.active.is_(True))).all()
    stored = {r.domain_no for r in rows}
    routed = {no for no, a in research.DOMAIN_AGENT_MAP.items() if a}
    assert stored == routed
    assert all(r.brief_version == BRIEF_CATALOGUE_VERSION for r in rows)


def test_the_prompt_uses_the_stored_brief_not_the_module(session):
    """The whole point of the move. Editing the stored row must change what an
    agent is sent, without touching code."""
    _seeded(session)
    session.execute(update(db.research_brief)
                    .where(db.research_brief.c.domain_no == 2)
                    .values(asks="COUNT THE PARCEL LOCKERS"))
    session.commit()

    briefs, plan_version = research.load_active_briefs(session)
    rendered = research._render_brief(2, "Acme Global Logistics", briefs=briefs)
    assert "COUNT THE PARCEL LOCKERS" in rendered
    assert plan_version.startswith("stored-")


def test_a_routed_domain_without_a_brief_fails_closed(session):
    """Researching on a bare domain name is the exact condition that produced
    group-level prose and homepage citations. It must not be reachable by
    deactivating a row."""
    _seeded(session)
    session.execute(update(db.research_brief)
                    .where(db.research_brief.c.domain_no == 2)
                    .values(active=False))
    session.commit()

    briefs, _ = research.load_active_briefs(session)
    with pytest.raises(research.BriefMissing, match="domain 2"):
        research.assert_brief_available(briefs, 2, "LLM-01")


def test_an_empty_table_falls_back_to_the_catalogue_and_says_so(session):
    """A database from before v19 keeps working. The plan version records that
    the code default was used, so a finding is not mistaken for one produced
    by a governed brief."""
    session.execute(db.research_brief.delete())
    session.commit()
    briefs, plan_version = research.load_active_briefs(session)
    assert briefs.keys() == RESEARCH_BRIEFS.keys()
    assert plan_version == f"code-{BRIEF_CATALOGUE_VERSION}"


def test_the_plan_version_changes_when_a_brief_changes(session):
    """A finding is only interpretable against the brief that produced it, so
    the run has to record which set was in force."""
    _seeded(session)
    _, before = research.load_active_briefs(session)

    session.execute(update(db.research_brief)
                    .where(db.research_brief.c.domain_no == 2)
                    .values(active=False))
    session.execute(insert(db.research_brief).values(
        brief_id="2-1.1.0", domain_no=2, brief_version="1.1.0",
        agent_id="LLM-01", asks="Revised", search=["x"], sources=[],
        active=True, approved_by="Priya Raman"))
    session.commit()

    _, after = research.load_active_briefs(session)
    assert before != after
