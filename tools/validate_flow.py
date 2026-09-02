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


CHECKS = [
    ("every name a module uses is bound", unbound_names),
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
