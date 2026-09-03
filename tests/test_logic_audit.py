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
    named assertions about a file nobody could import.

    Checks the module path, not the imported names. The first version read
    `from app.domain.policy import AnchorPolicy` as a module
    app.domain.AnchorPolicy and reported a class as a missing file - a false
    positive that cost a P0 verification.
    """
    import ast
    import pathlib

    here = pathlib.Path(__file__).resolve().parent
    domain = here.parent / "api_service" / "app" / "domain"
    if not domain.exists():
        return

    for path in sorted(here.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.ImportFrom) and node.module):
                continue
            parts = node.module.split(".")
            if parts[:2] != ["app", "domain"]:
                continue
            if len(parts) == 2:
                # `from app.domain import x, y` - each name is a module.
                for alias in node.names:
                    assert (domain / f"{alias.name}.py").exists(), (
                        f"{path.name} imports app.domain.{alias.name}, "
                        f"which does not exist")
            else:
                # `from app.domain.policy import AnchorPolicy` - the module is
                # policy and AnchorPolicy is a name inside it.
                assert (domain / f"{parts[2]}.py").exists(), (
                    f"{path.name} imports {node.module}, which does not exist")



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


@pytest.mark.parametrize("module", sorted(
    p.relative_to(APP).as_posix() for p in APP.rglob("*.py")),
    ids=lambda m: m)
def test_no_module_references_a_name_it_never_binds(module):
    """A NameError compiles clean, imports clean, and fails the first time the
    branch runs.

    `propose_split` used Decimal in a module that never imported it. py_compile
    passed, the import passed, and it failed as a 500 the first time an analyst
    pressed the button - after a full build and re-seed.

    This exact check already existed for the interface pages and was never run
    on the API modules, which is where the arithmetic lives.
    """
    import ast
    import builtins

    tree = ast.parse((APP / module).read_text())
    bound, used = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name):
            (bound if isinstance(node.ctx, (ast.Store, ast.Del))
             else used).add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global):
            bound.update(node.names)

    missing = sorted(used - bound - set(dir(builtins)))
    assert not missing, f"{module} uses {missing} and never binds them"


def test_no_code_reads_an_attribute_off_a_string_list_field():
    """`not_found` is declared list[str] and the coverage gate read
    `n.fact_class` off each entry - the shape the `facts` list has. Every sweep
    raised AttributeError: 'str' object has no attribute 'fact_class'.

    Written against an assumed shape rather than the declared one, and the test
    I wrote alongside it made the same assumption, so it asserted the same
    wrong thing.

    Done with the AST rather than a regex: the first version of this check
    matched only `for x in ...` and the defect was a set comprehension, so it
    passed on the exact code it was written to catch.
    """
    import ast

    schemas = ast.parse((APP / "llm" / "schemas.py").read_text())
    plain = {node.target.id for cls in schemas.body
             if isinstance(cls, ast.ClassDef)
             for node in cls.body
             if isinstance(node, ast.AnnAssign)
             and isinstance(node.target, ast.Name)
             and ast.unparse(node.annotation).startswith("list[str]")}
    assert plain, "no list[str] fields found - the sweep is not seeing them"

    offenders = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "schemas.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            pairs = [(g.target, g.iter)
                     for g in (getattr(node, "generators", None) or [])]
            if isinstance(node, ast.For):
                pairs = [(node.target, node.iter)]
            for target, iterated in pairs:
                if not isinstance(target, ast.Name):
                    continue
                source = ast.unparse(iterated)
                if not any(f".{field}" in source or source.endswith(field)
                           for field in plain):
                    continue
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Attribute)
                            and isinstance(inner.value, ast.Name)
                            and inner.value.id == target.id):
                        offenders.append(
                            f"{path.name}: iterates {source} (list[str]) and "
                            f"reads .{inner.attr}")
    assert not offenders, "\n".join(sorted(set(offenders)))


def test_every_return_from_one_function_has_the_same_arity():
    """Adding the runners-up to _best_footprint_fact's return left four of its
    five return paths at the old arity - each one an unpacking error on a real
    branch, and py_compile passes all of them.

    The three that fire on a missing or unusable fact are exactly the branches
    an analyst hits first on a new case.
    """
    import ast
    from collections import defaultdict

    offenders = []
    for path in sorted(APP.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arities = defaultdict(list)
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Return) and node.value is not None):
                    continue
                # a return inside a nested def belongs to that def
                inner = [n for n in ast.walk(fn)
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n is not fn
                         and n.lineno <= node.lineno <= (n.end_lineno or 0)]
                if inner:
                    continue
                value = node.value
                arity = (len(value.elts) if isinstance(value, ast.Tuple) else 1)
                arities[arity].append(node.lineno)
            # A function returning both a tuple and a bare value is the defect;
            # returning None early is normal and excluded above.
            if len(arities) > 1:
                offenders.append(
                    f"{path.name}::{fn.name} returns arities "
                    f"{ {k: v for k, v in sorted(arities.items())} }")
    assert not offenders, "\n".join(offenders)


def test_no_numeric_column_is_written_from_a_float():
    """float(Decimal("0.55")) round-trips as 0.55000000000000004440892098,
    which is strictly greater than 0.55 - so a share sitting exactly on a
    governed ceiling flips the wrong way.

    Three shares were stored this way, two of them feeding the 0.6A confidence
    components, and both call sites already had a Decimal in hand."""
    import re

    columns = set(re.findall(r'Column\("(\w+)",\s*Numeric',
                             (APP / "db.py").read_text()))
    assert columns, "no Numeric columns found - the sweep is blind"

    offenders = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        source = path.read_text()
        for column in columns:
            if f"{column}=float(" in source:
                offenders.append(f"{path.name}: {column}=float(...)")
    assert not offenders, "\n".join(sorted(offenders))


def test_the_float_round_trip_really_does_break_a_boundary():
    """The test above is only worth having if the risk is real."""
    from decimal import Decimal

    assert Decimal(float(Decimal("0.55"))) != Decimal("0.55")
    assert Decimal(float(Decimal("0.55"))) > Decimal("0.55")


def test_a_nested_function_is_not_swept_up_by_an_edit_to_its_parent():
    """The defect that broke the register for two releases.

    A script padding every return in `_best_footprint_fact` to a 3-tuple walked
    into its nested `_rejected` helper and appended `, "", []` there too. A
    non-empty tuple is always truthy, so `if _rejected(r)` rejected every
    registered Location footprint fact - the register was skipped on every
    case, and the reason shown to the analyst was the tuple itself:
    "3912.0000 sites: (None, '', [])".

    My own arity test excluded nested functions, which is exactly why it passed
    while this was broken. So this checks the opposite thing: a nested helper
    used as a predicate must not return a container.
    """
    import ast

    offenders = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for outer in ast.walk(tree):
            if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in outer.body:
                if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                used_as_test = any(
                    isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == inner.name
                    for node in ast.walk(outer)
                    for test in ([node.test] if isinstance(node, (ast.If, ast.While))
                                 else (node.ifs if isinstance(node, ast.comprehension)
                                       else []))
                    for call in ast.walk(test))
                if not used_as_test:
                    continue
                for node in ast.walk(inner):
                    if (isinstance(node, ast.Return) and node.value is not None
                            and isinstance(node.value,
                                           (ast.Tuple, ast.List, ast.Dict))):
                        offenders.append(
                            f"{path.name}::{outer.name}::{inner.name} L"
                            f"{node.lineno} returns a container and is used as "
                            f"a condition, so it is always truthy")
    assert not offenders, "\n".join(offenders)


def test_every_case_owned_lookup_is_scoped_to_the_case():
    """Audit finding C-04. The estimate route resolved a simulation by
    simulation_run_id alone, so case A's path plus case B's simulation id built
    A's estimate from B's estate - cross-case contamination, false provenance,
    and B's topology and site counts returned to a caller who asked about A.

    Three known-fact routes had the same defect in a weaker form: they took no
    case at all, so any fact on any case could be corroborated, rights-cleared
    or voided by id.

    A helper taking one column made the unscoped lookup the easy path. The
    check is on the call sites because that is where the omission happens.
    """
    import ast
    import re

    api = (APP / "routers" / "api.py").read_text()
    owned = set()
    for node in ast.parse((APP / "db.py").read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            columns = {c.args[0].value for c in ast.walk(node)
                       if isinstance(c, ast.Call)
                       and getattr(c.func, "id", "") == "Column"
                       and c.args and isinstance(c.args[0], ast.Constant)}
            if "case_id" in columns:
                owned.add(node.targets[0].id)
    assert owned, "no case-owned tables found - the sweep is blind"

    offenders = []
    for fn in [n for n in ast.parse(api).body
               if isinstance(n, ast.FunctionDef)]:
        body = ast.unparse(fn)
        takes_case = "case_id" in [a.arg for a in fn.args.args]
        for match in re.finditer(
                r"_one_or_404\([^,]+,\s*db\.(\w+),\s*db\.\1\.c\.\w+,\s*"
                r"[^,]+,\s*'[^']*'(.*?)\)", body, re.S):
            table, tail = match.group(1), match.group(2)
            if table not in owned or table == "case":
                continue
            if not takes_case:
                offenders.append(
                    f"{fn.name} resolves {table} with no case in its path")
            elif "owned_by_case" not in tail:
                offenders.append(
                    f"{fn.name} resolves {table} without owned_by_case")
    assert not offenders, "\n".join(offenders)


def test_the_lookup_helper_can_express_ownership():
    """A helper that takes one column makes the unscoped lookup the easy path
    and the scoped one a thing to remember."""
    import inspect

    from app.routers import api

    signature = inspect.signature(api._one_or_404)
    assert "owned_by_case" in signature.parameters
    source = inspect.getsource(api._one_or_404)
    assert "table.c.case_id == owned_by_case" in source
    # 404 rather than 403: whether a resource exists on another case is not
    # something a caller without access to that case should learn.
    assert "404" in source and "403" not in source


def test_the_validation_harness_refuses_to_score_synthetic_cases():
    """Audit finding A-01. An error statistic computed over cases somebody
    invented measures the inventor, and reporting it beside a real case as
    though they were the same number is the failure the evidence tier exists
    to prevent."""
    from app.domain import validation

    comparisons = [
        validation.compare({"case_id": "real",
                            "evidence_tier": validation.TIER_ACTUAL,
                            "actual": {"current_annual_cost": "1000"},
                            "estimated": {"current_annual_cost": "1200"}}),
        validation.compare({"case_id": "made-up",
                            "evidence_tier": validation.TIER_SYNTHETIC,
                            "actual": {"current_annual_cost": "1000"},
                            "estimated": {"current_annual_cost": "1000"}}),
    ]
    stats = validation.statistics(comparisons)
    assert stats["cases_included"] == 1
    assert stats["cases_excluded_as_synthetic"] == 1
    # the perfect synthetic case must not flatter the statistic
    assert stats["per_measure"]["current_annual_cost"]["n"] == 1


def test_an_empty_corpus_says_it_is_not_validated():
    """A harness with no cases validates nothing, and must not report silence
    as a pass."""
    from app.domain import validation

    note = validation.statistics([])["note"]
    assert "has not been empirically validated" in note


def test_the_statistics_report_direction_not_just_magnitude():
    """A model 30% high on half its cases and 30% low on the other half has a
    mean signed error near zero and is useless. Bias is the finding."""
    from app.domain import validation

    comparisons = [
        validation.compare({"case_id": str(i),
                            "evidence_tier": validation.TIER_ACTUAL,
                            "actual": {"current_annual_cost": "1000"},
                            "estimated": {"current_annual_cost": est}})
        for i, est in enumerate(("1300", "1300", "1300"))]
    m = validation.statistics(comparisons)["per_measure"]["current_annual_cost"]
    assert m["overestimated"] == 3 and m["underestimated"] == 0
    assert m["mean_signed_error"].startswith("300")


def test_a_missing_actual_is_not_scored_as_zero_error():
    """Absent evidence is not agreement."""
    from app.domain import validation

    out = validation.compare({"case_id": "partial",
                              "evidence_tier": validation.TIER_ACTUAL,
                              "actual": {"site_count": "340"},
                              "estimated": {"site_count": "340",
                                            "current_annual_cost": "9000"}})
    cost = next(r for r in out["rows"] if r["measure"] == "current_annual_cost")
    assert cost["status"] == "NOT_COMPARABLE"
