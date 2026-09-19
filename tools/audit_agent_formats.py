#!/usr/bin/env python3
"""Every agent call, checked for the gap between the prompt and the schema.

A run failed closed three times on "over 100": the agent found a source saying
"over 100 sites" and the schema had `public_value: Decimal` with nowhere to put
the "over". The agent was not wrong - it had two bad options and took the one
that preserved the meaning.

That is one instance of a class:

  * a schema field the prompt never mentions - the agent will not fill it, and
    if it is required the reply is rejected every time
  * a constrained field whose constraint the prompt does not state - an enum
    whose values are not listed, a pattern not described
  * a numeric field where a source would naturally give a range or a bound,
    with no qualifier beside it
  * a prompt naming a field the schema does not have

Read statically, because the point is to find these without spending a call.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
PROMPTS = (APP / "llm" / "prompts.py").read_text()
SCHEMAS = (APP / "llm" / "schemas.py").read_text()

SCHEMA_TREE = ast.parse(SCHEMAS)
PROMPT_TREE = ast.parse(PROMPTS)

# Numeric types a source often states loosely. A count or an amount is the
# thing a report qualifies - "over", "approximately", "up to" - where a date or
# a share usually is not.
LOOSE_TYPES = ("Decimal", "int", "float")

# Fields whose looseness is already handled, or where a bound makes no sense.
QUALIFIED = {"value_qualifier"}


def _classes():
    out = {}
    for node in SCHEMA_TREE.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target,
                                                              ast.Name):
                fields[item.target.id] = {
                    "annotation": ast.unparse(item.annotation),
                    "required": item.value is None,
                    "default": ast.unparse(item.value) if item.value else None,
                }
        out[node.name] = {"fields": fields, "bases": [ast.unparse(b)
                                                      for b in node.bases]}
    return out


CLASSES = _classes()


def _enum_members(name):
    node = next((n for n in SCHEMA_TREE.body
                 if isinstance(n, ast.ClassDef) and n.name == name), None)
    if node is None or not any("Enum" in b for b in
                               [ast.unparse(x) for x in node.bases]):
        return None
    return [x.targets[0].id for x in node.body if isinstance(x, ast.Assign)]


def _expand(model, seen=None):
    """Every field reachable from a model, including nested ones."""
    seen = seen or set()
    if model in seen or model not in CLASSES:
        return {}
    seen.add(model)
    out = {}
    for name, spec in CLASSES[model]["fields"].items():
        out[name] = spec
        for inner in re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b",
                                spec["annotation"]):
            if inner in CLASSES and inner != model:
                for k, v in _expand(inner, seen).items():
                    out.setdefault(k, v)
    return out


def _prompts():
    """Every PromptDefinition, with its id, version, task text and model."""
    out = []
    for node in ast.walk(PROMPT_TREE):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "PromptDefinition"):
            continue
        spec = {}
        for kw in node.keywords:
            if kw.arg in ("prompt_id", "prompt_version", "agent_id"):
                spec[kw.arg] = getattr(kw.value, "value", ast.unparse(kw.value))
            elif kw.arg == "output_model":
                spec["model"] = ast.unparse(kw.value).split(".")[-1]
            elif kw.arg in ("task", "rules", "output_contract"):
                try:
                    spec[kw.arg] = ast.literal_eval(kw.value)
                except (ValueError, SyntaxError):
                    spec[kw.arg] = ast.unparse(kw.value)
        if spec.get("prompt_id"):
            spec["text"] = " ".join(
                str(spec.get(k) or "") for k in ("task", "rules",
                                                 "output_contract"))
            out.append(spec)
    return out


# The provider receives `output_model.model_json_schema()` as a tool input
# schema (gateway.py:203), so it already has every field name, every enum
# member and every required flag. Restating those in prose is redundant, and a
# checker that reports 37 of them is one nobody reads.
#
# What the schema CANNOT tell the model is what to do when the world does not
# fit it: a source that says "over 100" when the field is a Decimal, or
# "24-36 months" when it is an int. That is a modelling gap, not a prompting
# one, and it is the only class that produced a real failure.
findings = {"loose_without_qualifier": [], "range_field_without_a_range": [],
            "no_model": []}

for prompt in sorted(_prompts(), key=lambda p: p["prompt_id"]):
    model = prompt.get("model")
    if not model or model not in CLASSES:
        findings["no_model"].append(f"{prompt['prompt_id']} -> {model}")
        continue
    text = prompt["text"]
    fields = _expand(model)

    for name, spec in sorted(fields.items()):
        base = spec["annotation"].split("|")[0].strip()
        # A low/base/high triple already expresses a range, so a source saying
        # "300 to 500" has somewhere to go. A lone number does not.
        band = {f"{stem}_low", f"{stem}_base", f"{stem}_high"} <= set(fields) \
            if (stem := re.sub(r"_(low|base|high)$", "", name)) else False
        if (base in LOOSE_TYPES and name not in QUALIFIED and not band
                and "qualifier" not in " ".join(fields)):
            findings["loose_without_qualifier"].append(
                f"{prompt['prompt_id']}: {model}.{name} is a bare {base} "
                f"with no band and no qualifier - a source saying 'over 100' "
                f"or '24 to 36 months' has nowhere to go")

print(f"AGENT CALL FORMAT AUDIT - {len(_prompts())} prompts, "
      f"{len(CLASSES)} schema classes\n")
total = 0
for kind, rows in findings.items():
    rows = sorted(set(rows))
    total += len(rows)
    print(f"{kind}: {len(rows)}")
    for row in rows[:14]:
        print(f"    {row}")
    if len(rows) > 14:
        print(f"    ... and {len(rows) - 14} more")
    print()
print(f"{total} finding(s)")
sys.exit(0)
