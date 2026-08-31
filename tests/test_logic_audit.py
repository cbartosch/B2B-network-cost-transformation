"""Audit guards: the inconsistencies a hundred incremental releases accumulated.

Each of these encodes a defect found by auditing the logic rather than by
hitting it. They are cheap, and every one of them is a class this codebase has
already produced at least once.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = next(c for c in (ROOT / "api_service" / "app", ROOT / "app")
           if (c / "routers" / "api.py").exists())
UI = ROOT / "analyst_ui" / "streamlit_app"


def test_the_simulation_version_moves_with_its_output_shape():
    """The page claims a re-run reproduces the output hash exactly. Adding
    bandwidth to the sample edges and sourcing the tier from a different table
    changed the hash while the version stayed at 1.1.0, making that claim false
    across builds - which is the defect the bump to 1.1.0 was itself
    introduced to fix."""
    config = (APP / "config.py").read_text()
    version = re.search(r'SIMULATION_MODEL_VERSION = "sim-([\d.]+)"', config)
    assert version, "the simulation model version is not declared"
    major, minor, _ = (version.group(1) + ".0").split(".")[:3]
    assert (int(major), int(minor)) >= (1, 2), (
        "edges carry bandwidth and the tier comes from archetype_bandwidth; "
        "that is at least sim-1.2.0")


def test_no_page_keeps_its_own_copy_of_a_governed_threshold():
    """A literal copy means a steward who retunes the governed value gets an
    interface that disagrees with the API about what will be accepted."""
    offenders = []
    for page in sorted(UI.rglob("*.py")):
        text = page.read_text()
        for name in ("max_sites_per_archetype_row", "material_spread_share",
                     "material_divergence_share", "max_attempts_per_call",
                     "min_addressable_share"):
            for line in text.splitlines():
                if name in line and re.search(r"=\s*\d", line) \
                        and "get(" not in line:
                    offenders.append(f"{page.name}: {line.strip()[:80]}")
    assert not offenders, offenders


def test_every_footprint_origin_the_resolver_emits_is_labelled():
    """And no origin is labelled that the resolver cannot emit - a dead label
    is a branch nobody can reach and nobody can tell is unreachable."""
    resolver = (APP / "domain" / "footprint.py").read_text()
    page = next(p for p in UI.rglob("*.py") if p.name.startswith("4_")).read_text()

    emitted = set(re.findall(r'"origin": "([A-Z_]+)"', resolver))
    labelled = set(re.findall(r'"([A-Z_]+)": \("', page))
    assert emitted <= labelled, f"origins with no label: {sorted(emitted - labelled)}"
    assert labelled <= emitted, f"labels for dead origins: {sorted(labelled - emitted)}"


def test_the_estimate_reads_the_drivers_the_interface_saves():
    """declared_users and declared_ops_cost_per_site were written to the case
    and read by nothing, so saving them changed no number - the same
    stored-and-inert defect that made researched quantities pointless before
    promotion existed."""
    api = (APP / "routers" / "api.py").read_text()
    assert "case_row.declared_users" in api
    assert "case_row.declared_ops_cost_per_site" in api


def test_no_business_quantity_is_defaulted_server_side():
    """900 per site reached the baseline whenever a caller omitted the field.
    A per-site operating cost nobody stated must not be costed as though
    somebody had."""
    api = (APP / "routers" / "api.py").read_text()
    assert 'Field(default=Decimal("900")' not in api
    assert "no ops cost per site" in api, (
        "omitting it has to be refused, not defaulted")


def test_the_research_prompt_quotes_the_bandwidth_the_model_will_use():
    """archetype_prior.bandwidth_mbps_base is overridden per industry from
    archetype_bandwidth. Reading the prior alone told the agent a tier the
    simulation would not apply - two sources of truth, and the agent was given
    the one that loses."""
    research = (APP / "domain" / "research.py").read_text()
    # Bounded by the next top-level def, not by a named one: _render_brief is
    # declared above _build_context, so slicing to it produced an empty string
    # and the assertion passed on nothing.
    import re as _re
    start = research.index("def _build_context")
    nxt = _re.search(r"^def ", research[start + 10:], _re.M)
    context = research[start:start + 10 + nxt.start()]
    assert "archetype_bandwidth" in context, (
        "the context builder must resolve the industry override")


@pytest.mark.parametrize("name", [
    "agent_quality_policy", "anchor_policy", "confidence_policy",
    "footprint_policy", "known_fact_policy", "price_divergence_policy",
    "research_budget_profile", "triangulation_policy",
])
def test_every_seeded_policy_set_is_consumed(name):
    """A governed value nobody reads is a control that does not exist, and it
    reads as one that does."""
    blob = "\n".join(p.read_text() for p in APP.rglob("*.py")
                     if p.name != "seed.py")
    assert f'"{name}"' in blob, f"{name} is seeded and read nowhere"


def test_no_function_rebinds_a_result_it_is_still_filling():
    """The defect that killed seven of seventeen domains in a live run.

    WP1 replaced a parsed dict with a Pydantic model and kept the variable
    name, which rebound the DomainResult the function had been filling since
    its first line. Every later `result.agent_run_id = ...` then assigned to a
    model whose config forbids extra fields, so the domain died with
    `"PublicEvidenceResult" object has no field "agent_run_id"` - and where the
    field did exist the write landed silently on the wrong object, which is
    worse."""
    research = (APP / "domain" / "research.py").read_text()
    start = research.index("result = DomainResult(")
    end = research.index("def ", start)
    body = research[start:end]
    assert "result, provenance = gateway.structured_call" not in body, (
        "structured_call must not bind to `result` while a DomainResult of "
        "that name is being filled")


def test_a_quantity_value_is_not_typed_as_a_decimal():
    """A domain whose honest answer is "2 halls, 2.75 MW" must not fail
    validation. Prose is a finding; the parse decides, not the schema."""
    schemas = (APP / "llm" / "schemas.py").read_text()
    block = schemas[schemas.index("class QuantityCandidate"):
                    schemas.index("class PublicEvidenceResult")]
    assert "value: Decimal" not in block, (
        "a Decimal here rejects the reply instead of classifying the answer")
    assert "value: str" in block


def test_promotion_will_not_price_a_string():
    promotion = (APP / "domain" / "promotion.py").read_text()
    assert "triangulate.parse_value" in promotion
    assert "stated in words" in promotion
