"""A source that qualifies its figure.

A run failed closed three times on "over 100": the agent found a source saying
"over 100 sites" and the schema had nowhere to put the "over", so the string
went into a Decimal field and every attempt was rejected.

That is a lower bound - real evidence, and the commonest way an annual report
states a count. Coercing it to 100 drops the word and understates; rejecting it
loses the source entirely.

Its own file, and every test reads source rather than importing: the natural
home, test_known_facts.py, has a module-level `from app.domain import
known_facts`, which imports sqlalchemy and blocks the whole file wherever it is
not installed - which is exactly where a schema guard needs to run.
"""
import ast
from pathlib import Path


def _app():
    root = Path(__file__).resolve().parents[1]
    return next(c for c in (root / "api_service" / "app", root / "app")
                if (c / "llm").exists())


def test_a_qualified_figure_has_somewhere_to_go():
    """A run failed closed three times on "over 100": the agent found a source
    saying "over 100 sites" and the schema had nowhere to put the "over", so
    the string went into a Decimal field and the reply was rejected.

    That is a lower bound - real evidence, and the commonest way an annual
    report states a count."""
    app = _app()
    tree = ast.parse((app / "llm" / "schemas.py").read_text())

    qualifier = next(n for n in tree.body
                     if isinstance(n, ast.ClassDef) and n.name == "ValueQualifier")
    members = {x.targets[0].id for x in qualifier.body
               if isinstance(x, ast.Assign)}
    assert members == {"EXACTLY", "AT_LEAST", "AT_MOST", "APPROXIMATELY"}

    candidate = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                     and n.name == "CorroborationCandidate")
    fields = {x.target.id for x in candidate.body
              if isinstance(x, ast.AnnAssign)}
    assert "value_qualifier" in fields
    # and the value itself stays a Decimal, so a bare string is still refused
    value = next(x for x in candidate.body if isinstance(x, ast.AnnAssign)
                 and x.target.id == "public_value")
    assert "Decimal" in ast.unparse(value.annotation)


def test_the_agent_is_told_how_to_express_a_bound():
    """A schema field the prompt does not mention is a field the agent will
    not use, and the reply will fail the same way."""
    import re

    app = _app()
    source = (app / "llm" / "prompts.py").read_text()

    start = source.index('prompt_id="known_fact.corroborate"')
    block = source[start:start + 3000]
    assert "value_qualifier" in block
    assert "AT_LEAST" in block
    # and the contract changed, so the version had to move
    assert re.search(r'prompt_version="2\.2\.0"', block)


def test_a_bound_is_not_compared_as_a_point():
    """A source saying "over 100" is consistent with an asserted 340.
    Comparing 100 against 340 would call the assertion contradicted by a
    source that says no such thing."""
    # Read from source, not imported. known_facts imports sqlalchemy and this
    # file is blocked on pydantic wherever neither is installed - which is
    # exactly where a schema guard needs to run. Fourth time this session.
    source = (_app() / "domain" / "known_facts.py").read_text()
    assert 'qualifier == "AT_LEAST" and target >= D(value)' in source
    assert 'qualifier == "AT_MOST" and target <= D(value)' in source
    assert "consistent_bound" in source


def test_a_candidate_without_a_qualifier_behaves_as_it_always_did():
    """Every reply before this change meant a precise figure, and a default of
    EXACTLY is what keeps them meaning that."""
    app = _app()
    tree = ast.parse((app / "llm" / "schemas.py").read_text())
    candidate = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                     and n.name == "CorroborationCandidate")
    field = next(x for x in candidate.body if isinstance(x, ast.AnnAssign)
                 and x.target.id == "value_qualifier")
    assert "EXACTLY" in ast.unparse(field.value)
