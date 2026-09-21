#!/usr/bin/env python3
"""Validate the data flow between stages.

Every functional defect in this build has been the same shape: one stage wrote
something and the next read something slightly different. A parameter renamed
and not updated at the call site. A dict key that moved. A classifier gaining a
target the bucket dict never got. A Decimal in a JSON column. A field the
prompt asked for that the schema forbade.

None of those are visible by reading one file, and none survive a check that
names the producer and the consumer and compares them. So this walks the
boundaries:

    intake      -> engagement_case columns
    register    -> known_fact -> footprint / archetype / estimate driver
    research    -> domain_disposition.evidence -> promotion candidates
    promotion   -> evidenced_footprint / _archetype / _anchor
    resolution  -> simulation inputs
    simulation  -> estimate components
    estimate    -> snapshot -> refinement

and reports three things per boundary: keys the producer emits, keys the
consumer reads, and any that appear on only one side.

Exit code is non-zero on a mismatch, so it can gate a build.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
UI = ROOT / "analyst_ui" / "streamlit_app"


def _read(*parts):
    return (APP.joinpath(*parts)).read_text()


def _sources():
    for path in sorted(APP.rglob("*.py")):
        yield path, path.read_text()


# --------------------------------------------------------------- table usage
def table_flow() -> list[str]:
    """A table written and never read is a stage that produces nothing."""
    problems = []
    tables = set(re.findall(r"^(\w+) = Table\(", _read("db.py"), re.M))
    blob = "\n".join(text for _p, text in _sources() if _p.name != "db.py")

    for table in sorted(tables):
        written = bool(re.search(rf"insert\(db\.{table}\)|update\(db\.{table}\)",
                                 blob))
        read = bool(re.search(rf"select\(db\.{table}[\.\)]", blob))
        if written and not read:
            problems.append(
                f"{table}: written and never read - the stage that fills it "
                f"produces nothing")
        if read and not written and table not in (
                "threshold", "archetype_prior", "platform_unit_cost", "lever",
                "assessment_question", "answer_option", "question_feature_map",
                "country_region", "topology_template", "archetype_bandwidth",
                "research_brief", "unit_cost_prior",
                # Governed reference data: filled by the seed and retuned by a
                # steward, never written by the application.
                "serviceability", "density_mix",
                # Exchange rates. Seed-only on purpose: a rate a steward
                # approved on a date is reproducible, and a case re-run next
                # week prices the same way. The application writing its own
                # rates would make an estimate a function of when it ran.
                "fx_rate",
                # Resilience per (industry, archetype). Derived from the
                # industry benchmark and the archetype baseline at seed time,
                # and stored rather than computed so a steward can inspect and
                # override one pair without rerunning a derivation.
                "archetype_resilience",
                # A supplied external benchmark. Seed-only by design: the
                # application must not write to it, because a published figure
                # edited in place stops being the published figure and nothing
                # would record that it changed.
                "industry_benchmark"):
            problems.append(
                f"{table}: read and never written outside the seed - the stage "
                f"that should fill it does not")
    return problems


# ------------------------------------------- classifier targets vs buckets
def classifier_targets() -> list[str]:
    """The defect that stopped archetype and anchor findings reaching anything:
    _classify gained targets and the bucket dict did not, so the list an
    analyst selects from was never built."""
    src = _read("domain", "promotion.py")
    classify = src[src.index("def _classify"):src.index("def candidates")]
    targets = set(re.findall(r'return "(\w+)"', classify))

    candidates = src[src.index("def candidates"):src.index("def promote")]
    buckets = set(re.findall(r'"(\w+)"',
                             candidates[candidates.index("buckets"):
                                        candidates.index("for entry in found")]))
    promote = src[src.index("def promote"):]
    handled = set(re.findall(r'if target == "(\w+)"', promote))

    problems = []
    for missing in sorted(targets - buckets - {"unclassified"}):
        problems.append(f"_classify returns {missing!r} with no candidate bucket")
    for missing in sorted(targets - handled - {"unclassified"}):
        problems.append(f"_classify returns {missing!r} and promote() has no "
                        f"branch for it")
    for surfaced in sorted(targets - {"unclassified"}):
        if f'"{surfaced}_candidates"' not in candidates:
            problems.append(f"{surfaced} candidates are bucketed but never "
                            f"returned, so nothing can select them")
    return problems


# ------------------------------------------------ evidenced_* to its consumer
def promotion_consumers() -> list[str]:
    """Each promotion target has to be read by the stage it feeds."""
    # A consumer may read the table directly or through an accessor, so both
    # count. Looking only for `db.<table>` reported the footprint resolver as
    # not reading evidenced_footprint when it reads it through
    # promotion.evidenced_footprint() - a false positive, and a check that
    # cries wolf is a check that stops being run.
    expected = {
        "evidenced_footprint": ("domain/footprint.py", "the footprint resolver",
                                ("db.evidenced_footprint",
                                 "promotion.evidenced_footprint")),
        "evidenced_archetype": ("domain/archetype.py", "the topology resolver",
                                ("db.evidenced_archetype",)),
        "evidenced_anchor": ("routers/api.py", "the ANCHOR estimate",
                             ("db.evidenced_anchor",)),
    }
    problems = []
    for table, (consumer, what, accessors) in expected.items():
        text = _read(*consumer.split("/"))
        if not any(a in text for a in accessors):
            problems.append(f"{table} is written by promotion and {what} "
                            f"({consumer}) never reads it")
    return problems


# ------------------------------------------- simulation output to the estimate
def simulation_to_estimate() -> list[str]:
    """The estimate reads the simulation's output by key. A key that moves here
    priced nothing and reported it as a coverage failure."""
    sim = _read("domain", "simulation.py")
    est = _read("domain", "estimate.py")
    api = _read("routers", "api.py")

    emitted = set(re.findall(r'"(\w+)":', sim[sim.index("return {"):]))
    problems = []
    for key in ("sites", "circuits", "products"):
        if key not in emitted:
            problems.append(f"simulation no longer emits {key!r}")
        if key not in est and key not in api:
            problems.append(f"simulation emits {key!r} and nothing reads it")
    # the bandwidth dimension has to survive into the priced product rows
    if "bandwidth_mbps" not in sim:
        problems.append("simulation does not carry bandwidth_mbps; a circuit "
                        "cannot be priced without its tier")
    return problems


# -------------------------------------------- provenance the interface reads
def provenance_contract() -> list[str]:
    """A caller displaying a field the gateway stopped returning is a stack
    trace on a successful run."""
    gateway = _read("llm", "gateway.py")
    call = gateway[gateway.index("def structured_call"):]
    problems = []
    ui = "\n".join(p.read_text() for p in UI.rglob("*.py"))
    for field in re.findall(r"p\.get\(['\"](\w+)['\"]\)", ui):
        if field in ("prompt_id", "prompt_version", "provider_response_id",
                     "input_tokens", "output_tokens", "latency_ms",
                     "model", "provider") and f'"{field}"' not in call:
            problems.append(f"the interface reads provenance[{field!r}] and "
                            f"structured_call does not return it")
    return problems


# ------------------------------------------------- prompt asks vs schema holds
def prompt_schema_agreement() -> list[str]:
    """Asking for a field and then refusing it is the worst of both, and it
    cost a 377-second domain three times over."""
    prompts = _read("llm", "prompts.py")
    # Both halves. The contract was split into a core every service reads and a
    # research part only the six that search or cite sources read, and this
    # check named the old single constant - so it crashed rather than passing
    # falsely, which is the right failure but still a failure.
    contract = prompts[prompts.index("CORE_CONTRACT = "):
                       prompts.index("class ToolPolicy")]
    schemas = _read("llm", "schemas.py")
    tree = ast.parse(schemas)
    fields = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            fields[node.name] = {
                n.target.id for n in node.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}

    problems = []
    asked = {f for f in ("source_class", "how_read", "figure_basis")
             if f in contract}
    for model in ("SourceRef", "QuantityCandidate", "CorroborationCandidate",
                  "BenchmarkObservationOut", "ProposedKnownFact"):
        missing = asked - fields.get(model, set())
        if missing:
            problems.append(f"the contract asks every source for "
                            f"{sorted(missing)} and {model} forbids extras "
                            f"without declaring them")
    return problems


# --------------------------------------------------- case fields to consumers
def case_fields() -> list[str]:
    """A field intake collects and nothing reads is a question asked for
    nothing."""
    db = _read("db.py")
    block = db[db.index("case = Table("):db.index("schema=\"engagement\"")]
    columns = set(re.findall(r'Column\("(\w+)"', block))
    blob = "\n".join(text for _p, text in _sources() if _p.name != "db.py")
    ignore = {"case_id", "created_at", "created_by", "archived", "archived_by"}
    problems = []
    for column in sorted(columns - ignore):
        if not re.search(rf"\b{column}\b", blob):
            problems.append(f"case.{column} is collected at intake and read "
                            f"nowhere")
    return problems


def unbound_names() -> list[str]:
    """A name used and never bound anywhere in the module.

    A NameError compiles clean, imports clean, and fails the first time the
    branch runs - `propose_split` used Decimal in a module that never imported
    it, and it surfaced as a 500 after a full build and re-seed. The same check
    existed for the interface pages and had never been run on the API modules,
    which is where the arithmetic lives.
    """
    import builtins

    problems = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
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
        # Module builtins Python provides. __file__ in particular: a module
        # that locates a file beside itself needs it, and reporting that is
        # the kind of false positive that teaches people to ignore a checker.
        #
        # Parenthesised: `a - b - c | d` unions d back in after subtracting,
        # which reported every module builtin as missing rather than none.
        missing = sorted(used - bound
                         - (set(dir(builtins))
                            | {"__file__", "__name__", "__doc__",
                               "__package__"}))
        if missing:
            problems.append(f"{path.name} uses {missing} and never binds them")
    return problems


def pinned_run_params() -> list[str]:
    """Everything the job runner reads from a run's params must be pinned.

    The runner rebuilds a resumed pass from `params`, so a key it reads and the
    endpoint never writes is silently absent - and absent is not the same as
    empty for anything with a fallback. Pinning serviceability was written once
    and the replacement did not match, so the runner rebuilt an empty table and
    every site in the estate came back unserviceable: "10 sites in URBAN DE
    cannot be served at all", which is impossible.
    """
    api = _read("routers", "api.py")
    jobs = _read("jobs.py")
    start = api.index('params={"footprint"')
    block = api[start:api.index("status=jobs.QUEUED", start)]
    pinned = set(re.findall(r'"(\w+)":', block))
    read = set(re.findall(r'row\.params or \{\}\)\.get\("(\w+)"\)', jobs))
    return [f"the runner reads params[{k!r}] and the endpoint never pins it"
            for k in sorted(read - pinned)]


def seeded_keys_are_columns() -> list:
    """Every key the seed writes must be a column of the table it writes to.

    `price_basis` was added to db.py by a blind single-occurrence replace that
    hit `Column("approved", ...)` in platform_unit_cost instead of
    unit_cost_prior, while the seed wrote the key to both. The API then refused
    to start - correctly - and the compose output said only "exited (3)".

    A seed key that is not a column is an insert that cannot succeed, and it
    fails at startup on a fresh database rather than in review.
    """
    columns = {}
    for node in ast.parse(_read("db.py")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            cols = {a.args[0].value for a in ast.walk(node)
                    if isinstance(a, ast.Call)
                    and getattr(a.func, "id", "") == "Column"
                    and a.args and isinstance(a.args[0], ast.Constant)}
            if cols:
                columns[node.targets[0].id] = cols

    seed = _read("seed.py")
    problems = []
    # Each (table, lambda: [ {..} for .. ]) block, bounded by its own `for`
    # clause so two adjacent blocks cannot be read as one.
    for match in re.finditer(
            r"\((\w+), lambda: \[\s*(\{[^\[\]]*?\})\s*\n\s*for ",
            seed, re.S):
        table, literal = match.group(1), match.group(2)
        keys = set(re.findall(r'"(\w+)":', literal))
        known = columns.get(table)
        if known is None:
            continue                      # not a Table object; a policy tuple
        unknown = sorted(keys - known)
        if unknown:
            problems.append(
                f"seed writes {unknown} to {table}, which has no such column")
    return problems


def ensemble_carries_what_it_computes() -> list:
    """A value computed on every pass and dropped by the aggregate.

    C-05: implied_users, bandwidth_profile and bandwidth_mbps_total were
    computed per pass and never returned, so the estimate's derived-headcount
    branch was unreachable and every request without a typed headcount was
    refused - which reads as a missing input rather than a lost one.
    """
    tree = ast.parse(_read("domain", "simulation.py"))

    def returned(name):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        keys = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                keys |= {k.value for k in node.value.keys
                         if isinstance(k, ast.Constant)}
        return keys

    # Carried under another name on purpose: a per-pass count becomes a
    # percentile band, and the samples become one topology.
    renamed = {"dual_sites", "circuits_per_site", "nodes", "edges",
               "site_sample", "estate_full"}
    lost = sorted(returned("one_pass") - returned("aggregate") - renamed)
    return [f"one_pass computes {k!r} and aggregate drops it" for k in lost]


def no_orphaned_domain_module() -> list:
    """A domain module nothing imports is a document, not a control.

    The four-class access vocabulary shipped with twenty passing tests and
    nothing importing it - every symbol read `used by: nothing`, and the model
    went on pricing an IPVPN at 100/30 on the 100. Same shape as
    `fx_convention` collected and never read.

    Handles `from . import x` as well as `from .x import y`: a relative package
    import has module=None, and the first three versions of this check missed
    it - reporting a wired module as orphaned, which is the failure mode that
    makes a checker ignorable.
    """
    domain = APP / "domain"
    if not domain.exists():
        return []
    modules = {p.stem for p in domain.glob("*.py")} - {"__init__"}
    importers = {m: set() for m in modules}

    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None or node.module.split(".")[-1] == "domain":
                # `from . import access` / `from .domain import access`
                for alias in node.names:
                    if alias.name in modules and path.stem != alias.name:
                        importers[alias.name].add(path.stem)
            elif node.module.split(".")[-1] in modules:
                base = node.module.split(".")[-1]
                if path.stem != base:
                    importers[base].add(path.stem)

    # A module only a tool imports is not wired into the running system, and is
    # reported separately rather than passing quietly.
    tool_only = set()
    for path in (ROOT / "tools").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in modules and not importers[alias.name]:
                        tool_only.add(alias.name)

    # domain/validation.py is deliberately tool-only: it compares estimator
    # output against cases with known actuals, which is an audit activity
    # rather than part of producing an estimate. Named here rather than
    # excluded by a rule, so adding a second tool-only module is a decision
    # somebody makes on purpose.
    DELIBERATELY_TOOL_ONLY = {"validation"}

    return [f"nothing in the application imports domain/{m}.py"
            + (" (only a tool does)" if m in tool_only else "")
            for m in sorted(modules)
            if not importers[m] and m not in DELIBERATELY_TOOL_ONLY]


def dataclass_defaults_come_last() -> list:
    """A defaulted field before a non-defaulted one is a TypeError at import.

    Adding `unsourced_price_share_trigger` after `set_name` in 4.161.0 put
    eleven non-defaulted fields behind a defaulted one, so
    domain/policy.py could not be imported at all - and neither could
    coverage or confidence, which import it.

    It stayed hidden for eleven releases because nothing in this environment
    could import those modules to find out. py_compile passes: the class body
    is valid syntax and the error is raised when @dataclass processes it.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not (isinstance(node, ast.ClassDef)
                    and any("dataclass" in ast.unparse(d)
                            for d in node.decorator_list)):
                continue
            defaulted = None
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                if item.value is not None:
                    defaulted = item.target.id
                elif defaulted:
                    problems.append(
                        f"{path.name}::{node.name}: {item.target.id!r} has no "
                        f"default and follows {defaulted!r} which does - the "
                        f"module cannot be imported")
                    break
    return problems


def enum_members_gates_name_exist() -> list:
    """Rejection.X where the enum declares no X.

    quality.py named `Rejection.OPTION_NOT_SUPPLIED` and the enum did not
    define it, so the gate raised AttributeError instead of returning a
    governed rejection - the reply was refused for the wrong reason and the run
    recorded a crash rather than a finding.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        enums = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    "Enum" in ast.unparse(b) for b in node.bases):
                enums[node.name] = {
                    item.targets[0].id for item in node.body
                    if isinstance(item, ast.Assign)
                    and isinstance(item.targets[0], ast.Name)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and getattr(node.value, "id", "") in enums
                    and node.attr not in enums[getattr(node.value, "id")]
                    and not node.attr.startswith("_")
                    and node.attr not in ("value", "name")):
                problems.append(
                    f"{path.name}:{node.lineno} names "
                    f"{node.value.id}.{node.attr} and the enum does not "
                    f"declare it - AttributeError instead of a governed "
                    f"outcome")
    return problems


def policies_validate_their_own_fields() -> list:
    """A validate() checking a field its class does not declare.

    The transport-retry bound was checked in QualityPolicy, which does not
    declare the field - so it validated an attribute always absent there, and
    AgentQualityPolicy, which owns it, accepted any budget.
    """
    problems = []
    source = (APP / "domain" / "policy.py").read_text()
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef):
            continue
        declared = {item.target.id for item in node.body
                    if isinstance(item, ast.AnnAssign)}
        declared |= {t.id for item in node.body
                     if isinstance(item, ast.Assign)
                     for t in item.targets if isinstance(t, ast.Name)}
        validate = next((m for m in node.body
                         if isinstance(m, ast.FunctionDef)
                         and m.name == "validate"), None)
        if validate is None:
            continue
        for inner in ast.walk(validate):
            if (isinstance(inner, ast.Attribute)
                    and getattr(inner.value, "id", "") == "self"
                    and inner.attr not in declared
                    and not inner.attr.startswith("_")):
                problems.append(
                    f"{node.name}.validate checks self.{inner.attr}, which "
                    f"{node.name} does not declare - the check never sees the "
                    f"field and the class that owns it is unvalidated")
    return problems


def release_identity_agrees() -> list:
    """VERSION and _version.py must declare the same release.

    They were kept in sync by hand and drifted to 4.31.0 against 4.198.0 - 167
    releases, with /v1/health reporting the old one.

    My first version of this check forbade the literal and required
    _version.py to read VERSION at import. That fixed the drift and broke
    something else: a release number that exists only at runtime cannot be
    read by a static auditor, an SBOM or a diff, and an external audit
    reported the build identity as missing entirely.

    So both are literals and `tools/set_release.py` writes them together. The
    check enforces what actually matters - that they agree - rather than a
    particular mechanism for keeping them agreeing.
    """
    version_file = ROOT / "VERSION"
    module = APP / "_version.py"
    if not version_file.exists() or not module.exists():
        return []
    declared = re.search(r"build:\s*([0-9A-Za-z.\-+]+)", version_file.read_text())
    build = re.search(r'^BUILD\s*=\s*"([^"]+)"', module.read_text(), re.M)
    if build is None:
        return ["_version.py declares no BUILD literal - a value computed at "
                "import cannot be read by a static auditor, an SBOM or a diff"]
    if declared is None:
        return ["VERSION declares no build"]
    if declared.group(1) != build.group(1):
        return [f"release identity disagrees: VERSION={declared.group(1)} but "
                f"_version.py={build.group(1)}. /v1/health reports the second, "
                f"so an operator would be told the wrong release. "
                f"`python3 tools/set_release.py <release>` writes both."]
    return []


def class_attributes_a_classmethod_reads_exist() -> list:
    """A classmethod reading cls.X where the class defines no X.

    `ConfidencePolicy.COMPONENTS`, `.STAGES`, `.BASELINE_DRIVERS` and
    `.TARGET_DRIVERS` were lost in 4.173.0: the edit that moved two defaulted
    fields to the end of the class trimmed lines from the bottom of the body
    and took the class constants with them. The same edit ate the @classmethod
    decorator, which I noticed and put back, and these which I did not.

    from_rows reads all four, so every call raised AttributeError and no
    confidence score could be produced. The class imports fine - which is why
    nothing caught it - and it is the third defect of that shape in this file
    alone.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            defined = {t.id for item in node.body
                       if isinstance(item, ast.Assign)
                       for t in item.targets if isinstance(t, ast.Name)}
            defined |= {item.target.id for item in node.body
                        if isinstance(item, ast.AnnAssign)}
            methods = {item.name for item in node.body
                       if isinstance(item, ast.FunctionDef)}
            # Attributes a base class provides. This flagged
            # `cls.model_fields` on a pydantic model, which BaseModel defines
            # - the check reads one class at a time and cannot see up the
            # hierarchy, and a checker that reports a working line is one
            # people stop reading.
            #
            # Named rather than "skip anything with a base", because the
            # defect it catches - ConfidencePolicy losing five class
            # constants - was on a class with a base too.
            if any(ast.unparse(base).endswith(("BaseModel", "Strict", "Enum"))
                   for base in node.bases):
                methods |= {"model_fields", "model_config", "model_validate",
                            "model_dump", "model_json_schema", "__fields__"}
            used = {n.attr for n in ast.walk(node)
                    if isinstance(n, ast.Attribute)
                    and getattr(n.value, "id", "") == "cls"}
            for missing in sorted(used - defined - methods):
                problems.append(
                    f"{path.name}::{node.name} reads cls.{missing} and defines "
                    f"no {missing} - every call raises AttributeError, and the "
                    f"class imports fine so nothing catches it until a route "
                    f"runs")
    return problems


def seeded_bandwidths_are_priceable() -> list:
    """An (industry, archetype) bandwidth with no rate tier at or above it.

    The BICS benchmark put a supermarket store at 275 Mbps while the card
    quoted consumer access at 50 and 100 only, so every store in every retail
    estate was unpriced scope - 2% coverage for a French grocer, 15% for a
    German discounter, and the gate correctly refusing to price the rest.
    match_prior takes the cheapest tier at or above the requirement and never
    substitutes downward, so a bandwidth above every tier is unpriceable
    rather than approximated.

    Nothing caught it because the pricing tests use industries whose figures
    happen to land on a quoted tier. This checks all of them.
    """
    seed_source = (APP / "seed.py").read_text()

    # Imported, not sliced: ARCHETYPE_BANDWIDTH and PRIORS are computed
    # expressions rather than literal lists, so reading the text finds a
    # prefix and misses the rows appended to it.
    import importlib.machinery
    import sys
    import types as _types

    for library in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc",
                    "sqlalchemy.engine", "sqlalchemy.dialects",
                    "sqlalchemy.dialects.postgresql", "psycopg"):
        stub = _types.ModuleType(library)
        stub.__getattr__ = lambda _n: type("A", (), {
            "__getattr__": lambda s, _x: s,
            "__call__": lambda s, *a, **k: s})()
        stub.__spec__ = importlib.machinery.ModuleSpec(library, loader=None)
        sys.modules.setdefault(library, stub)
    sys.path[:0] = [str(ROOT), str(ROOT / "api_service")]
    try:
        from app import seed as seed_module
    except Exception as exc:                                # noqa: BLE001
        return [f"the seed could not be imported to check its bandwidths: "
                f"{type(exc).__name__}"]

    product_of = {row[0]: row[4] for row in seed_module.ARCHETYPES}
    tiers = {}
    for country, product, _layer, mbps, *_rest in seed_module.PRIORS:
        tiers.setdefault(product, set()).add(int(mbps))

    problems = []
    for industry, archetype, mbps in seed_module.ARCHETYPE_BANDWIDTH:
        product = product_of.get(archetype)
        if product is None:
            # An archetype with no prior profile is priced through whatever
            # the estimate assigns it; not this check's business.
            continue
        quoted = tiers.get(product, set())
        if not quoted:
            problems.append(
                f"{industry}/{archetype} is a {product} and no country prices "
                f"that product at all")
            continue
        if not any(tier >= int(mbps) for tier in quoted):
            problems.append(
                f"{industry}/{archetype} needs {mbps} Mbps of {product} and "
                f"the highest tier quoted anywhere is {max(quoted)} - every "
                f"site of this type is unpriced scope")
    return problems


def every_country_prices_what_its_estates_need() -> list:
    """A product an estate needs that one country in scope cannot price.

    The check above asks "does *any* country quote this tier" and passes while
    a specific country cannot. ETHERNET 250 exists in the US, so it passed -
    and France and the Netherlands quote no Ethernet at all and no DIA above
    500 Mbps, which is why a Dutch and French estate came back 67% covered
    while the same estate in the US covered 100%.

    A global check hiding a per-country gap is the same shape as the defect it
    was written to catch.

    Reported per country rather than per industry: the fix is a rate row in a
    market, not a change to an industry.
    """
    import importlib.machinery
    import sys
    import types as _types

    for library in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc",
                    "sqlalchemy.engine", "sqlalchemy.dialects",
                    "sqlalchemy.dialects.postgresql", "psycopg"):
        stub = _types.ModuleType(library)
        stub.__getattr__ = lambda _n: type("A", (), {
            "__getattr__": lambda s, _x: s,
            "__call__": lambda s, *a, **k: s})()
        stub.__spec__ = importlib.machinery.ModuleSpec(library, loader=None)
        sys.modules.setdefault(library, stub)
    sys.path[:0] = [str(ROOT), str(ROOT / "api_service")]
    try:
        from app import seed as seed_module
    except Exception as exc:                                # noqa: BLE001
        return [f"the seed could not be imported: {type(exc).__name__}"]

    product_of = {row[0]: row[4] for row in seed_module.ARCHETYPES}
    backup_of = {row[0]: row[5] for row in seed_module.ARCHETYPES}

    # Two-letter scopes only. A region is a deliberate fallback for a country
    # with no card of its own, and holding it to the same completeness would
    # report every region as broken.
    tiers = {}
    countries = set()
    for country, product, _layer, mbps, *_rest in seed_module.PRIORS:
        tiers.setdefault((country, product), set()).add(int(mbps))
        if len(country) == 2:
            countries.add(country)

    # What a PRIMARY circuit can ask for. Backups are excluded: a 5G backup at
    # 50 Mbps behind a 275 Mbps primary is a deliberate degraded path, not a
    # missing rate, and pairing a backup product with the primary's bandwidth
    # reported fourteen such pairs as gaps.
    wanted = set()
    for industry, archetype, mbps in seed_module.ARCHETYPE_BANDWIDTH:
        product = product_of.get(archetype)
        if product:
            wanted.add((product, int(mbps)))

    # And only where the bearer can actually be delivered. Singapore quotes no
    # cable broadband because Singapore has no cable network - serviceability
    # records that, the model substitutes fibre, and reporting it as a pricing
    # gap is reporting a market that does not exist.
    deliverable = set()
    for country, _band, technology, available, _mbps in (
            seed_module.SERVICEABILITY):
        if available:
            deliverable.add((country, technology))
    legacy = {}
    try:
        from app.domain.access import LEGACY_PRODUCT
        legacy = {product: pair[1] for product, pair in LEGACY_PRODUCT.items()}
    except Exception:                                       # noqa: BLE001
        pass

    # The whole fallback chain, not the country alone. Since the workbook
    # loaded, 71 countries have GPON and HFC of their own and take DIA from
    # their region - so asking per country reported every one of them as a
    # pricing gap when the ladder answers.
    from app.domain.scope import REGION_PARENT
    region_of = dict(seed_module.COUNTRY_REGION)

    def _chain(country):
        sub = region_of.get(country)
        return [c for c in (country, sub, REGION_PARENT.get(sub) if sub else None)
                if c]

    problems = []
    for country in sorted(countries):
        missing = []
        for product, mbps in sorted(wanted):
            technology = legacy.get(product)
            if technology and (country, technology) not in deliverable:
                # Not deliverable here, so not a pricing gap.
                continue
            if not any(tier >= mbps
                       for scope in _chain(country)
                       for tier in tiers.get((scope, product), set())):
                missing.append((product, mbps))
        if missing:
            shown = ", ".join(f"{p} {m}" for p, m in missing[:4])
            problems.append(
                f"{country} cannot price {len(missing)} (product, bandwidth) "
                f"pair(s) its estates can ask for - {shown}"
                + (f" and {len(missing) - 4} more" if len(missing) > 4 else "")
                + ". An estate in this country is unpriced scope wherever it "
                  "needs one of these, whatever another country quotes.")
    return problems


def no_local_shadows_an_imported_module() -> list:
    """A function that assigns `x` and also reads `x.attr` from an import.

    `run_estimate` assigns a local called `scope` at line 3393 and read
    `scope.REGION_PARENT` at 3324. Python decides local-or-global per function
    rather than per line, so the earlier read was an unbound local and every
    estimate raised UnboundLocalError.

    The unbound-names check one function up does not catch this: `scope` IS
    bound in that function, just later. That is the whole trap.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        imported = set()
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assigned, attribute_reads = {}, {}
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Name)
                        and isinstance(inner.ctx, ast.Store)
                        and inner.id in imported):
                    assigned.setdefault(inner.id, inner.lineno)
                elif (isinstance(inner, ast.Attribute)
                      and isinstance(inner.value, ast.Name)
                      and inner.value.id in imported):
                    attribute_reads.setdefault(
                        inner.value.id, []).append(inner.lineno)
            for name, first_assignment in assigned.items():
                earlier = [n for n in attribute_reads.get(name, [])
                           if n < first_assignment]
                if earlier:
                    problems.append(
                        f"{path.name}::{node.name} assigns a local `{name}` at "
                        f"line {first_assignment} and reads `{name}.` at "
                        f"{earlier[0]} - the import is shadowed for the whole "
                        f"function, so the earlier read is an unbound local")
    return problems


def columns_read_are_columns() -> list:
    """`row.foo` on a SELECT of a table that has no `foo`.

    `preflight.input_digest` asked a known_fact row for `fact_id` and `value`;
    the table has `known_fact_id` and a low/base/high triple. Every pre-flight
    run raised AttributeError as soon as a case had a fact - and it shipped,
    because the test fixture was a hand-written class carrying the attributes
    the code wanted rather than the columns the table has.

    Only checks a loop whose source table is unambiguous: `for x in
    session.execute(select(db.TABLE)...)` followed by `x.attr`. A row built
    from a join or a column list is out of scope here, because guessing the
    source would produce false positives and a checker people ignore.
    """
    db_source = (APP / "db.py").read_text()
    columns = {}
    for match in re.finditer(r"^(\w+) = Table\(", db_source, re.M):
        table, start = match.group(1), match.start()
        end = db_source.index("schema=", start)
        columns[table] = set(
            re.findall(r'Column\("(\w+)"', db_source[start:end]))

    problems = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.comprehension, ast.For)):
                continue
            target = node.target
            if not isinstance(target, ast.Name):
                continue
            iterated = ast.unparse(node.iter)
            found = re.search(r"select\(db\.(\w+)\)", iterated)
            if not found or found.group(1) not in columns:
                continue
            table = found.group(1)
            # Only within THIS comprehension or loop body. Walking the whole
            # module matched every `r` in the file against every table and
            # reported nine tables for one line - a checker that cries wolf
            # is one people switch off, which is the note on the term-factor
            # work two modules over.
            if isinstance(node, ast.comprehension):
                # the comprehension's own element and conditions
                scope_nodes = list(node.ifs)
                for outer in ast.walk(tree):
                    if isinstance(outer, (ast.ListComp, ast.SetComp,
                                          ast.GeneratorExp)) and \
                            node in outer.generators:
                        scope_nodes.append(outer.elt)
                    elif isinstance(outer, ast.DictComp) and \
                            node in outer.generators:
                        scope_nodes.extend([outer.key, outer.value])
            else:
                scope_nodes = list(node.body)

            for scope_node in scope_nodes:
                for inner in ast.walk(scope_node):
                    if not isinstance(inner, ast.Attribute):
                        continue
                    if (isinstance(inner.value, ast.Name)
                            and inner.value.id == target.id
                            and inner.attr not in columns[table]
                            and not inner.attr.startswith("_")
                            and inner.attr not in ("count", "index", "keys")):
                        problems.append(
                            f"{path.name}:{inner.lineno} reads .{inner.attr} "
                            f"from a {table} row and {table} has no such "
                            f"column - AttributeError at runtime, and a "
                            f"hand-written test fixture will not catch it")
    return sorted(set(problems))


def seeded_values_fit_their_type() -> list:
    """A seeded value the column cannot hold fails the whole seed.

    `transition_policy.evidence_grade = "E"` went into
    reference.threshold.value, which is Numeric(12,4). One row out of
    eighty-four, and it took the other eighty-three with it - the seed aborts
    on the insert, so a database gets no thresholds at all and every policy
    read then reports an incomplete governed set.

    Checked against the declared column type rather than by trying the insert,
    because the insert needs a database and this has to fail in the build.
    """
    from decimal import Decimal, InvalidOperation

    problems = []
    db_source = (APP / "db.py").read_text()
    seed_source = (APP / "seed.py").read_text()

    # Which columns are numeric, per table.
    numeric = {}
    for match in re.finditer(r"^(\w+) = Table\(", db_source, re.M):
        table = match.group(1)
        start = match.start()
        end = db_source.index("schema=", start)
        for column in re.finditer(
                r'Column\("(\w+)",\s*(Numeric|Integer|Float)', db_source[start:end]):
            numeric.setdefault(table, set()).add(column.group(1))

    # The seeded tuple lists whose rows carry a value into one of them.
    for name, table, index in (("THRESHOLDS", "threshold", 2),):
        if f"{name} = [" not in seed_source:
            continue
        start = seed_source.index(f"{name} = [")
        namespace = {}
        try:
            exec(seed_source[start:seed_source.index("\n]\n", start) + 3],
                 namespace)
        except Exception:                                   # noqa: BLE001
            problems.append(f"{name} could not be read to check its values")
            continue
        if "value" not in numeric.get(table, set()):
            continue
        for row in namespace[name]:
            try:
                Decimal(str(row[index]))
            except (InvalidOperation, TypeError, ValueError):
                problems.append(
                    f"{name} seeds {row[0]}.{row[1]} = {row[index]!r} into "
                    f"{table}.value, which is numeric - the insert fails and "
                    f"takes every other row with it")
    return problems


def every_constructed_class_can_be_constructed() -> list:
    """A class whose classmethod calls cls(field=...) needs a generated init.

    `FootprintPolicy` lost its @dataclass in 4.165.0 - TransitionPolicy was
    inserted immediately above and the insertion consumed the decorator line.
    A plain class has no __init__ taking keywords, so from_rows raised
    "FootprintPolicy() takes no arguments" and page 5 could not resolve a
    footprint at all.

    It survived 28 releases because the class *imports* fine and nothing in the
    offline suite constructs one. The 4.173 check missed it by construction: it
    inspected field ordering on classes that had the decorator, so a class
    without one was never examined.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            decorated = any("dataclass" in ast.unparse(d)
                            for d in node.decorator_list)
            if decorated:
                continue
            # Does anything inside construct it with keywords?
            keyword_construction = any(
                isinstance(inner, ast.Call)
                and getattr(inner.func, "id", "") == "cls"
                and inner.keywords
                for inner in ast.walk(node))
            declares_fields = any(isinstance(item, ast.AnnAssign)
                                  for item in node.body)
            has_init = any(isinstance(item, ast.FunctionDef)
                           and item.name == "__init__" for item in node.body)
            if keyword_construction and declares_fields and not has_init:
                problems.append(
                    f"{path.name}::{node.name} calls cls(field=...) and has "
                    f"neither @dataclass nor an __init__ - constructing it "
                    f"raises TypeError at runtime, and the class imports fine "
                    f"so nothing catches it until a route calls it")
    return problems


CHECKS = [
    ("every name a module uses is bound", unbound_names),
    ("dataclass defaults come last", dataclass_defaults_come_last),
    ("every constructed class can be constructed",
     every_constructed_class_can_be_constructed),
    ("every seeded value fits its column type", seeded_values_fit_their_type),
    ("every seeded bandwidth has a tier that can price it",
     seeded_bandwidths_are_priceable),
    ("every country prices what its estates need",
     every_country_prices_what_its_estates_need),
    ("every cls attribute a classmethod reads exists",
     class_attributes_a_classmethod_reads_exist),
    ("every enum member a gate names exists", enum_members_gates_name_exist),
    ("a policy validates only fields it declares",
     policies_validate_their_own_fields),
    ("release identity agrees", release_identity_agrees),
    ("no orphaned domain module", no_orphaned_domain_module),
    ("the ensemble carries what it computes", ensemble_carries_what_it_computes),
    ("every column a query reads exists", columns_read_are_columns),
    ("no local shadows an imported module it also uses",
     no_local_shadows_an_imported_module),
    ("every seeded key is a column", seeded_keys_are_columns),
    ("every run param the runner reads is pinned", pinned_run_params),
    ("tables written and read", table_flow),
    ("classifier targets reach a bucket, a branch and the interface",
     classifier_targets),
    ("each promotion target has a consumer", promotion_consumers),
    ("simulation output keys the estimate reads", simulation_to_estimate),
    ("provenance the interface displays", provenance_contract),
    ("the prompt asks only for fields the schema holds", prompt_schema_agreement),
    ("case fields reach a consumer", case_fields),
]


def main() -> int:
    failures = 0
    for name, check in CHECKS:
        try:
            problems = check()
        except Exception as exc:                          # noqa: BLE001
            print(f"[ERROR] {name}: the check itself failed: "
                  f"{type(exc).__name__}: {exc}")
            failures += 1
            continue
        if problems:
            print(f"[FAIL]  {name}")
            for problem in problems:
                print(f"          - {problem}")
            failures += len(problems)
        else:
            print(f"[ok]    {name}")
    print()
    if failures:
        print(f"{failures} boundary problem(s). Each is one stage writing "
              f"something the next does not read.")
        return 1
    print("Every stage boundary agrees on what crosses it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
