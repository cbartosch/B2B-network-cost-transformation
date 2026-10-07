"""The location structure is assessed, not looked up.

The first attempt was a static table of asks per industry. That is the thing
that does not need an agent: if the questions are fixed, a table answers
them.

What a table cannot do is know that DHL says "Packstation" and "Paketshop",
that Royal Mail says "Post Office" and "parcel locker", or that a forecourt
retailer counts sites its industry peers do not have. Those are the terms a
search has to use - nobody publishes a count of "SELF_SERVICE_TERMINAL" - and
they are company-specific, not industry-specific.

So LLM-10 works out the estate and GENERATES the searches. The static table
remains as the floor for a case where the agent has not run.
"""
from pathlib import Path


def test_the_agent_is_registered():
    from app.llm import registry

    assert "LLM-10" in registry.AGENTS
    assert "location structure" in registry.AGENTS["LLM-10"]["name"]


def test_the_prompt_exists_and_is_bound_to_its_schema():
    from app.llm import prompts, schemas

    found = [d for d in prompts._DEFS
             if d.prompt_id == "llm10.location_structure.assess"]
    assert found, "the prompt must be registered"
    assert found[0].output_model is schemas.LocationStructureResult
    # tool_policy is a (tool, version) tuple - ("web_search", "1.0.0") - not
    # an object with .name. The attribute access raised AttributeError, so the
    # search requirement this test exists for was never actually checked.
    tool, _version = found[0].tool_policy
    assert tool == "web_search", (
        "an assessment of a company's estate has to search")


def test_the_agent_generates_the_queries_rather_than_receiving_them():
    """The whole point. A prompt that hands the agent a fixed list of
    questions is a static table with extra steps."""
    from app.llm import prompts

    task = next(d for d in prompts._DEFS
                if d.prompt_id == "llm10.location_structure.assess").task
    assert "generate the SEARCHES" in task.upper() or \
        "GENERATE THE SEARCHES" in task.upper()
    assert "its own words" in task.lower() or "OWN WORDS" in task.upper()


def test_a_site_class_carries_the_companys_own_term():
    from app.llm import schemas

    fields = schemas.SiteClass.model_fields
    assert "company_term" in fields
    assert "suggested_queries" in fields
    assert "archetype" in fields, "it must map to the model's vocabulary"


def test_a_count_may_be_a_bound_not_only_a_point():
    """"Over 15,000 Packstations" is how these are actually published, and a
    bare int throws the "over" away."""
    from app.llm import schemas

    assert "count_qualifier" in schemas.SiteClass.model_fields


def test_an_unmappable_class_is_returned_unmapped_rather_than_forced():
    """A class forced into the wrong site type is worse than one left
    unmapped, because the wrong one prices."""
    from app.llm import prompts, schemas

    assert schemas.SiteClass.model_fields["archetype"].default is None
    task = next(d for d in prompts._DEFS
                if d.prompt_id == "llm10.location_structure.assess").task
    assert "leave `archetype` null" in task


def test_the_quality_gate_refuses_an_unactionable_answer():
    """An assessment that names classes and no searches is the static table
    again, and one that counts without a source propagates an unsourced
    number into the footprint."""
    from app.llm import quality

    assert "llm10.location_structure.assess" in quality.RULES


def test_the_dominant_class_is_asked_for_separately_from_the_largest():
    """A handful of sortation hubs can outweigh thirty thousand lockers."""
    from app.llm import prompts, schemas

    assert "dominant_class" in schemas.LocationStructureResult.model_fields
    task = next(d for d in prompts._DEFS
                if d.prompt_id == "llm10.location_structure.assess").task
    assert "not the most numerous" in task


def test_what_it_could_not_determine_is_named():
    """A class the agent knows exists but could not count is a finding;
    omitting it makes the estate look complete."""
    from app.llm import schemas

    assert "unresolved" in schemas.LocationStructureResult.model_fields


def test_the_static_asks_remain_as_the_floor():
    """For a case where the agent has not run. A blank brief is worse than a
    generic one - but the agent's answer supersedes it."""
    from app.domain import industry_asks

    assert industry_asks.SITE_TYPE_ASKS
    assert "DC" in industry_asks.ALWAYS_ASK
