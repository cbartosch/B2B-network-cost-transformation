"""LLM-11 pressure-tests a finished estimate. Advisory, never a gate.

Two kinds of defect reached the analyst in the session that produced this
agent. One kind was caught by deterministic checks before shipping: a PLANT
on DIA, four missing fallback bandwidths, five invented column names, a
vacuous test, an ungated prompt.

The other kind was caught by a person looking at a screen: 3,800 data centres
in one country, 19,000 large offices for a parcel carrier, 233 registered
branches coming back as 60, a 1.21bn baseline with every gate green.

Every one of the second kind is a world-knowledge judgement, and no rule
existed because nobody had thought to write one. That is the gap this agent
fills - and the reason its most important output is the proposed CHECK, not
the finding.
"""
from pathlib import Path


def test_the_agent_is_registered_and_the_prompt_is_bound():
    from app.llm import prompts, registry, schemas

    assert "LLM-11" in registry.AGENTS
    found = [d for d in prompts._DEFS if d.prompt_id == "llm11.estimate.review"]
    assert found
    assert found[0].output_model is schemas.EstimateReview


def test_the_reviewer_gathers_no_new_evidence():
    """A second opinion drawn from the same judgement is not a second
    opinion. It reviews what it is given."""
    from app.llm import prompts

    definition = next(d for d in prompts._DEFS
                      if d.prompt_id == "llm11.estimate.review")
    assert definition.tool_policy == prompts.ToolPolicy.NONE


def test_it_is_advisory_and_says_so():
    """Reproducibility is the system's headline property: the same inputs
    give the same answer. A non-deterministic reviewer in the publication
    path means the same estimate passes on Tuesday and fails on Wednesday."""
    from app.llm import prompts, schemas

    task = next(d for d in prompts._DEFS
                if d.prompt_id == "llm11.estimate.review").task
    assert "ADVISORY" in task
    assert "coverage gate decides" in task
    doc = schemas.EstimateReview.__doc__ or ""
    assert "never a gate" in doc.lower()


def test_every_material_concern_must_propose_a_check():
    """A finding fixes one estimate; a rule fixes every future one. The
    session that produced this agent worked exactly that way - a person
    spotted something, it became a deterministic check."""
    from app.llm import schemas

    assert "suggested_rule" in schemas.EstimateConcern.model_fields


def test_a_review_of_nothing_is_refused():
    """An agent asked whether something looks right usually says yes, and a
    number that looks reviewed is more dangerous than one nobody believes."""
    from app.llm import quality

    assert "llm11.estimate.review" in quality.RULES

    class _Empty:
        concerns = []
        checked_and_sound = []
        headline_caveat = "fine"
    verdict = quality.RULES["llm11.estimate.review"](_Empty())
    assert not verdict.accepted


def test_a_material_concern_without_a_rule_is_refused():
    from app.llm import quality

    class _Concern:
        material = True
        suggested_rule = None

    class _Result:
        concerns = [_Concern()]
        checked_and_sound = ["coverage"]
        headline_caveat = "something"
    assert not quality.RULES["llm11.estimate.review"](_Result()).accepted


def test_the_caveat_is_required():
    """The system knows its weaknesses in structured form and states them in
    fragments across four screens. The paragraph a partner repeats is the
    main output."""
    from app.llm import quality, schemas

    assert "headline_caveat" in schemas.EstimateReview.model_fields

    class _NoCaveat:
        concerns = []
        checked_and_sound = ["coverage"]
        headline_caveat = None
    assert not quality.RULES["llm11.estimate.review"](_NoCaveat()).accepted


def test_it_reports_what_it_checked_and_found_sound():
    """A list of problems with no denominator tells a reader nothing about
    breadth."""
    from app.llm import schemas

    assert "checked_and_sound" in schemas.EstimateReview.model_fields


def test_the_prompt_names_the_defects_that_motivated_it():
    """Written down so a future reader knows what class of thing to look
    for, rather than inferring it from the word 'review'."""
    from app.llm import prompts

    task = next(d for d in prompts._DEFS
                if d.prompt_id == "llm11.estimate.review").task
    assert "3,800 data centres" in task
    assert "nobody had thought to write the rule" in task
