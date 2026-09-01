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


def test_no_schema_object_is_treated_as_a_domain_result():
    """The defect that killed seven of seventeen domains: structured_call bound
    to `result`, rebinding the DomainResult the function was filling, so every
    later field write hit a model that forbids extra fields.

    Checked structurally rather than by name, so renaming the variable back
    would fail this."""
    import ast

    src = (APP / "domain" / "research.py").read_text()
    fields = {"agent_run_id", "disposition", "reason", "failed",
              "failure_detail", "budget_note", "verified_sources",
              "queries_used", "captures_used", "triangulated", "qualitative"}
    offenders = []
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        bound = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if getattr(func, "attr", getattr(func, "id", "")) == "structured_call":
                    for target in node.targets:
                        elts = target.elts if isinstance(target, ast.Tuple) else [target]
                        for elt in elts[:1]:
                            if isinstance(elt, ast.Name):
                                bound.add(elt.id)
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in bound and node.attr in fields):
                offenders.append(f"{fn.name} line {node.lineno}: "
                                 f"{node.value.id}.{node.attr}")
    assert not offenders, offenders


def test_every_domain_result_attribute_is_in_its_slots():
    """__slots__ makes a typo an AttributeError rather than a silent new
    attribute, which is the point - but only if the two stay in step."""
    import ast

    src = (APP / "domain" / "research.py").read_text()
    for cls in ast.walk(ast.parse(src)):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "DomainResult"):
            continue
        slots, assigned = set(), set()
        for node in ast.walk(cls):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__slots__":
                        slots = {e.value for e in node.value.elts}
                    if (isinstance(target, ast.Attribute)
                            and getattr(target.value, "id", "") == "self"):
                        assigned.add(target.attr)
            if (isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Attribute)
                    and getattr(node.target.value, "id", "") == "self"):
                assigned.add(node.target.attr)
        assert not assigned - slots, f"missing from __slots__: {sorted(assigned - slots)}"
        return
    pytest.fail("DomainResult not found")


def test_confirming_an_entity_never_wipes_a_typed_identifier():
    """Confirmation locks entity_identifier, and it wrote cand.identifier
    unconditionally - so confirming a candidate the agent found without one
    wiped a hand-typed LEI and left a mandatory field permanently empty,
    unfillable without re-resolving.

    The candidate is the better source when it has one and no source at all
    when it does not."""
    src = (APP / "domain" / "entity_resolution.py").read_text()
    confirm = src[src.index("def confirm("):src.index("def profile(")]
    assert "cand.identifier or (" in confirm, (
        "a null identifier on the candidate must not overwrite the case's")
    assert "identifier_source" in confirm
    assert "identifier_note" in confirm, (
        "an empty identifier after a locking confirmation has to be reported "
        "at that moment, not discovered at pre-flight")


def test_no_test_is_vacuous():
    """753 test functions is only reassuring if each of them can fail.

    A test asserting a literal, or comparing two constants, passes forever and
    reads as coverage. Tests that assert nothing at all are allowed here when
    they fail by raising - `policy.validate()`, `py_compile(doraise=True)`, a
    helper that calls pytest.fail - because "this does not raise" is a real
    check, just an implicit one.
    """
    import ast
    import pathlib

    RAISES_ON_FAILURE = ("validate(", "doraise", "pytest.fail", "_assert_json",
                         "model_validate", "pytest.raises", "compile(")
    tests_dir = pathlib.Path(__file__).resolve().parent
    vacuous, total = [], 0

    for path in sorted(tests_dir.rglob("test_*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef)
                    and fn.name.startswith("test_")):
                continue
            total += 1
            body = ast.get_source_segment(source, fn) or ""
            asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]

            for node in asserts:
                test = node.test
                if isinstance(test, ast.Constant) and test.value:
                    vacuous.append(f"{path.name}::{fn.name} asserts a literal")
                elif isinstance(test, ast.Compare) and all(
                        isinstance(c, ast.Constant)
                        for c in [test.left, *test.comparators]):
                    vacuous.append(
                        f"{path.name}::{fn.name} compares two constants")

            if not asserts and not any(h in body for h in RAISES_ON_FAILURE):
                vacuous.append(
                    f"{path.name}::{fn.name} neither asserts nor raises")

    assert total > 500, f"only {total} tests found - the sweep is not seeing them"
    assert not vacuous, "\n".join(vacuous)


def test_no_module_defines_the_same_name_twice():
    """An external audit found this; I had done it twice in one session.

    Python silently keeps the last definition, so a duplicate is not an error -
    it is a working module in which an earlier definition has been replaced by
    an unrelated one. In 4.123 that produced: two EstimateAnswer schemas whose
    surviving pair raised AttributeError on every gate call; two ClearRightsIn
    and two PrefillIn models, so two working endpoints silently took a request
    model written for a different route; and a second _migrate_v21, so the
    column it added was never added by any step.

    None of that is visible by reading either definition. All of it is visible
    in one pass over the module's top level.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers" / "api.py").exists())

    offenders = []
    for path in sorted(app.rglob("*.py")):
        seen = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                seen.setdefault(node.name, []).append(node.lineno)
        for name, lines in seen.items():
            if len(lines) > 1:
                offenders.append(
                    f"{path.name}: {name} defined at lines {lines}")
    assert not offenders, "\n".join(offenders)


def test_every_migration_number_is_registered_exactly_once():
    """A second function with an existing step's name loses the collision and
    its column is never added - the reconciler then supplies it and logs a
    warning saying a step did not take effect, which is a control doing a
    migration's job."""
    import re

    src = (APP / "migrations.py").read_text()
    registered = re.findall(r"(\d+): _migrate_v(\d+)", src)
    for key, fn in registered:
        assert key == fn, f"step {key} is mapped to _migrate_v{fn}"
    numbers = sorted(int(k) for k, _ in registered)
    assert len(numbers) == len(set(numbers)), "a step number is registered twice"
    expected = list(range(numbers[0], numbers[-1] + 1))
    assert numbers == expected, (
        f"gap in the migration chain: {sorted(set(expected) - set(numbers))}")
    declared = int(re.search(r"SCHEMA_VERSION = (\d+)", src).group(1))
    assert declared == numbers[-1], (
        f"SCHEMA_VERSION is {declared} and the last step is {numbers[-1]}")


def test_a_guard_precedes_the_code_that_needs_its_value():
    """`mbps` was read at the comparison and assigned by the guard below it -
    an UnboundLocalError on the first price candidate, and on later ones the
    *previous* candidate's bandwidth, which silently priced a circuit at a tier
    from a different finding."""
    src = (APP / "domain" / "promotion.py").read_text()
    guard = src.index('mbps = q.get("bandwidth_mbps")')
    use = src.index("bandwidth_mbps=int(mbps)")
    assert guard < use, "the bandwidth guard must run before the comparison"


def test_no_two_modules_implement_the_same_thing():
    """4.124.0 removed a duplicated class, gate and route and left both first
    implementations in place - domain/explain.py, tests/test_explain.py, a
    second prompt id, a gate mapping for it, and a dead import. The
    same-module duplicate check passed because they sat in different files.

    Two modules exporting the same function names for the same purpose is the
    same defect one directory up, and it survives every per-file check.
    """
    import ast
    import pathlib
    from collections import defaultdict

    root = pathlib.Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers" / "api.py").exists())

    # A signature is the set of public functions a domain module exports.
    # Names shared by chance are common; a whole overlapping set is not.
    exports = {}
    for path in sorted((app / "domain").glob("*.py")):
        names = {n.name for n in ast.parse(path.read_text()).body
                 if isinstance(n, ast.FunctionDef)
                 and not n.name.startswith("_")}
        if len(names) >= 2:
            exports[path.name] = names

    overlaps = []
    modules = sorted(exports)
    for i, first in enumerate(modules):
        for second in modules[i + 1:]:
            shared = exports[first] & exports[second]
            smaller = min(len(exports[first]), len(exports[second]))
            if shared and len(shared) >= max(2, smaller * 0.6):
                overlaps.append(
                    f"{first} and {second} both export {sorted(shared)}")
    assert not overlaps, "\n".join(overlaps)


def test_every_registered_prompt_is_gated_and_every_gate_has_a_prompt():
    """A gate mapping for a prompt that no longer exists is dead governance
    that reads as live, and an ungated prompt is a call nobody judges."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "llm").exists())
    registered = set(re.findall(
        r'prompt_id="([\w.]+)",\n\s*prompt_version',
        (app / "llm" / "prompts.py").read_text()))
    gated = set(re.findall(r'"([\w.]+)": \w+,',
                           (app / "llm" / "quality.py").read_text()))
    gated = {g for g in gated if "." in g}
    assert not registered - gated, f"ungated: {sorted(registered - gated)}"
    assert not gated - registered, (
        f"gated but no longer registered: {sorted(gated - registered)}")


def test_no_test_file_targets_a_module_that_no_longer_exists():
    """tests/test_explain.py survived the module it tested, so six failures
    named assertions about a file nobody could import."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent
    app_root = root.parent
    for path in sorted(root.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.startswith("app.domain")):
                continue
            for alias in node.names:
                candidate = (app_root / "api_service" / "app" / "domain"
                             / f"{alias.name}.py")
                if candidate.parent.exists():
                    assert candidate.exists() or alias.name in ("policy",), (
                        f"{path.name} imports app.domain.{alias.name}, "
                        f"which does not exist")


# ----------------------------------------- duplication, in every shape it took
def test_no_two_handlers_share_a_verb_and_path():
    """Two ask_about_estimate handlers both decorated the same POST path.
    FastAPI registers both and routes to the first, so the second is dead code
    that reads as live - and Python had already replaced the first by name."""
    import re
    from collections import Counter

    routes = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"',
                        (APP / "routers" / "api.py").read_text())
    clashes = [f"{v.upper()} {p}" for (v, p), n in Counter(routes).items() if n > 1]
    assert not clashes, clashes


def test_no_test_name_appears_in_two_files():
    """A shared name makes a failure report ambiguous about which test failed,
    which cost real time reading the 146-failure list. Distinct behaviour
    deserves a distinct name."""
    import ast
    import pathlib
    from collections import defaultdict

    seen = defaultdict(list)
    for path in sorted(pathlib.Path(__file__).resolve().parent.glob("test_*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                seen[node.name].append(path.name)
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not clashes, "\n".join(f"{k} in {v}" for k, v in sorted(clashes.items()))


def test_no_two_migrations_add_the_same_column():
    """Two _migrate_v21 functions existed and one lost the name collision, so
    its column was never added. Two steps adding the same column is the same
    mistake with both surviving - the second is a no-op that reads as work."""
    import ast
    import re
    from collections import defaultdict

    bodies = defaultdict(list)
    for node in ast.parse((APP / "migrations.py").read_text()).body:
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("_migrate_v")):
            continue
        columns = tuple(sorted(re.findall(
            r'_add_column\(conn, db\.(\w+), "(\w+)"', ast.unparse(node))))
        if columns:
            bodies[columns].append(node.name)
    clashes = {k: v for k, v in bodies.items() if len(v) > 1}
    assert not clashes, "\n".join(
        f"{v} all add {list(k)}" for k, v in clashes.items())


def test_no_class_name_is_defined_in_two_modules():
    """Distinct from the same-module check: two EstimateAnswer classes in one
    file were caught by that, and two modules each defining one would not be."""
    import ast
    from collections import defaultdict

    where = defaultdict(set)
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                where[node.name].add(path.name)
    clashes = {k: sorted(v) for k, v in where.items() if len(v) > 1}
    assert not clashes, "\n".join(f"{k} in {v}" for k, v in sorted(clashes.items()))


def test_no_panel_heading_appears_on_two_pages():
    """Two "Ask about this estimate" panels lived on the same page and were
    caught per-page. The same heading on two different pages is the same
    duplicated feature, one level out."""
    import pathlib
    import re
    from collections import defaultdict

    ui = pathlib.Path(__file__).resolve().parents[1] / "analyst_ui" / "streamlit_app"
    where = defaultdict(set)
    for path in sorted(ui.rglob("*.py")):
        for heading in re.findall(r'st\.subheader\("([^"]+)"\)', path.read_text()):
            where[heading].add(path.name)
    clashes = {k: sorted(v) for k, v in where.items() if len(v) > 1}
    assert not clashes, "\n".join(f"{k!r} on {v}" for k, v in sorted(clashes.items()))
