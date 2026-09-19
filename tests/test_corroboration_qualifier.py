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


# ------------------- the same gap in the extractor that feeds the rate card
def test_the_benchmark_extractor_can_express_a_bound():
    """A systematic audit of all eleven agent calls found the same defect in
    llm09.benchmark.extract, which feeds unit_cost_prior.

    A tariff page is the likeliest place to meet a qualified figure - "from
    GBP 250 a month", "prices start at" - and an entry price recorded as a
    market price understates the card every European estate derives from."""
    tree = ast.parse((_app() / "llm" / "schemas.py").read_text())
    observation = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                       and n.name == "BenchmarkObservationOut")
    fields = {x.target.id for x in observation.body
              if isinstance(x, ast.AnnAssign)}
    assert "value_qualifier" in fields
    assert "term_months_basis" in fields


def test_the_qualifier_reaches_the_table():
    """A field the agent fills and the table drops is the defect this audit
    was looking for."""
    db_source = (_app() / "db.py").read_text()
    start = db_source.index("benchmark_observation = Table(")
    end = db_source.index("schema=", start)
    assert '"value_qualifier"' in db_source[start:end]

    ingest = (_app() / "domain" / "benchmark_ingest.py").read_text()
    assert "value_qualifier=(r.get(\"value_qualifier\")" in ingest


def test_a_bound_does_not_distort_a_derived_band():
    """"From GBP 250" tells you the market does not go below 250. It says
    nothing about the middle or the top, and averaging it with exact
    observations pulls the band down towards an entry price."""
    ingest = (_app() / "domain" / "benchmark_ingest.py").read_text()
    assert 'qualifier in ("AT_LEAST", "AT_MOST")' in ingest
    assert "bounds.append" in ingest


def test_the_extractor_prompt_was_versioned_with_the_contract():
    """A schema field the prompt does not mention is a field the agent will
    not use, and the reply fails the same way."""
    import re

    prompts = (_app() / "llm" / "prompts.py").read_text()
    start = prompts.index('prompt_id="llm09.benchmark.extract"')
    block = prompts[start:start + 3000]
    assert "value_qualifier" in block
    assert re.search(r'prompt_version="2\.1\.0"', block)


def test_the_audit_tool_runs_and_finds_the_known_remainder():
    """Four findings remain on PublicEvidenceResult, where Quantity.value is
    already a string - so a qualified figure has somewhere to go and the risk
    is lower. A checker whose result nobody records drifts."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, str(root / "tools" / "audit_agent_formats.py")],
        capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr[:400]
    assert "finding(s)" in out.stdout
    remaining = int(out.stdout.rsplit("\n", 2)[-2].split()[0])
    # 20 at 4.223.0: 4 loose numeric fields on PublicEvidenceResult, where
    # Quantity.value beside them is already a string, and 16 unbounded lists
    # across six prompts. The one that actually truncated is fixed; the rest
    # are the same failure waiting for a large enough answer.
    #
    # A ceiling rather than a target. It must not grow unnoticed, and lowering
    # it is the work.
    assert remaining <= 20, (
        f"{remaining} format findings, up from the 20 known at 4.223.0")


# ---------------------- an unbounded reply truncates at any budget
def test_the_public_evidence_reply_is_bounded():
    """llm01.public_evidence.extract was cut off at 8,000 tokens after 114
    seconds - the governed budget, working correctly since 4.192.0.

    The reply nests: quantities x candidates grows multiplicatively, and the
    prompt said "return everything you find", "put every number", "list EVERY
    one". The agent was doing exactly what it was told. Raising the budget
    moves where it truncates; only a bound makes the reply finite."""
    tree = ast.parse((_app() / "llm" / "schemas.py").read_text())
    for cls, field in (("PublicEvidenceResult", "quantities"),
                       ("PublicEvidenceResult", "sources"),
                       ("Quantity", "candidates")):
        node = next(n for n in tree.body
                    if isinstance(n, ast.ClassDef) and n.name == cls)
        spec = next(x for x in node.body if isinstance(x, ast.AnnAssign)
                    and x.target.id == field)
        assert "max_length" in ast.unparse(spec.value), f"{cls}.{field}"


def test_the_cap_being_reached_is_reported():
    """A thin answer because the market is thin and a thin answer because the
    cap was hit are different findings, and only the second is worth another
    call. Without a counter they look identical."""
    tree = ast.parse((_app() / "llm" / "schemas.py").read_text())
    result = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                  and n.name == "PublicEvidenceResult")
    quantity = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                    and n.name == "Quantity")
    assert "quantities_omitted" in {x.target.id for x in result.body
                                    if isinstance(x, ast.AnnAssign)}
    assert "candidates_omitted" in {x.target.id for x in quantity.body
                                    if isinstance(x, ast.AnnAssign)}


def test_the_instruction_keeps_its_intent_and_gains_a_ceiling():
    """"Do not average them, pick between them or drop the ones you find less
    convincing" is right - the spread and the vintage are more informative
    than any single figure. What it lacked was a ceiling and a way to say the
    ceiling had been reached."""
    import re

    prompts = (_app() / "llm" / "prompts.py").read_text()
    start = prompts.index('prompt_id="llm01.public_evidence.extract"')
    block = prompts[start:start + 3600]
    assert "Do not average them" in block, "the original intent must survive"
    assert "at most 12 quantities" in block
    assert "never the ones you find most convincing" in block
    assert re.search(r'prompt_version="2\.5\.0"', block)
