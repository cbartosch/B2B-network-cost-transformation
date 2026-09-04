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
                "serviceability", "density_mix"):
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
        missing = sorted(used - bound - set(dir(builtins)))
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


CHECKS = [
    ("every name a module uses is bound", unbound_names),
    ("no orphaned domain module", no_orphaned_domain_module),
    ("the ensemble carries what it computes", ensemble_carries_what_it_computes),
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
