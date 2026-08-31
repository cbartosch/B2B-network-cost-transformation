#!/usr/bin/env python3
"""Push a realistic reply for every agent-routed domain through the pipeline.

pydantic is not installable in this sandbox, so the models are reconstructed
from the schema source: field names, optionality and enum members are read from
the AST and enforced the way `extra="forbid"` would. That catches the exact
class of failure this build keeps hitting - a field the prompt asks for that
the model does not declare, a required field left null, an enum value outside
its set - without pretending to be pydantic.

Everything downstream is the real code: triangulate, reliability and the
promotion classifier are pure Python and are imported and run, not simulated.
The evidence blob each domain would store is JSON-serialised at the end,
because that is where two releases died.
"""
import ast
import json
import pathlib
import re
import sys
import types
from decimal import Decimal as D

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"


# --------------------------------------------------------------- schema model
def load_models():
    """Field sets and enum members, read from the schema source."""
    tree = ast.parse((APP / "llm" / "schemas.py").read_text())
    models, enums = {}, {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}
        if "Enum" in bases or "str" in bases:
            members = [n.value.value for n in node.body
                       if isinstance(n, ast.Assign)
                       and isinstance(n.value, ast.Constant)]
            if members:
                enums[node.name] = set(members)
                continue
        fields = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields[item.target.id] = {
                    "annotation": ast.unparse(item.annotation),
                    "required": item.value is None,
                }
        if fields:
            models[node.name] = fields
    return models, enums


MODELS, ENUMS = load_models()


class Invalid(Exception):
    pass


def validate(model_name, payload, path="") -> None:
    """Enforce field sets, requiredness and enum membership, as forbid would."""
    spec = MODELS[model_name]
    extra = sorted(set(payload) - set(spec))
    if extra:
        raise Invalid(f"{path or model_name}: extra inputs not permitted: {extra}")
    for field, meta in spec.items():
        if meta["required"] and payload.get(field) is None:
            raise Invalid(f"{path or model_name}.{field}: field required")
        value = payload.get(field)
        if value is None:
            continue
        annotation = meta["annotation"]
        for enum_name, members in ENUMS.items():
            if enum_name in annotation and value not in members:
                raise Invalid(f"{path or model_name}.{field}: {value!r} not in "
                              f"{sorted(members)}")
        for nested in MODELS:
            if re.search(rf"\b{nested}\b", annotation):
                items = value if isinstance(value, list) else [value]
                for i, item in enumerate(items):
                    if isinstance(item, dict):
                        validate(nested, item, f"{path or model_name}.{field}.{i}")
                break


# ------------------------------------------------------- downstream, for real
sys.path.insert(0, str(APP.parent))


def _load(module):
    """Import a pure-Python domain module without its package."""
    src = (APP / "domain" / f"{module}.py").read_text()
    ns = {"Decimal": D, "statistics": __import__("statistics"),
          "uuid": __import__("uuid"), "re": re, "D": lambda v: D(str(v))}
    body = src[src.index("\n\n", src.index('"""', src.index('"""') + 3)):]
    body = "\n".join(l for l in body.splitlines()
                     if not l.startswith(("from ", "import ")))
    exec(body, ns)
    return ns


TRI = _load("triangulate")
REL = _load("reliability")

POLICY = types.SimpleNamespace(
    material_spread_share=D("0.15"), stale_after_years=3,
    min_independent_sources_material_fact=2)


def _classify(q):
    """The real classifier, with its module constants supplied."""
    src = (APP / "domain" / "promotion.py").read_text()
    ns = {"triangulate": types.SimpleNamespace(parse_value=TRI["parse_value"]),
          "ARCHETYPES": {"BRANCH", "STORE", "WAREHOUSE", "LARGE_OFFICE", "DC"},
          "PRODUCTS": {"DIA", "MPLS", "ETHERNET", "BROADBAND_HFC",
                       "BROADBAND_PON", "MOBILE_5G"}}
    exec(src[src.index("def _classify"):src.index("def candidates")], ns)
    return ns["_classify"](q)


# ------------------------------------------------------------- the 17 domains
def _src(publisher, cls, read="FULL_PAGE", basis="STATED", year="2025"):
    return {"url": f"https://example.test/{publisher.lower().replace(' ', '-')}",
            "publisher": publisher, "as_of": year, "source_class": cls,
            "how_read": read, "figure_basis": basis,
            "excerpt": f"{publisher} states the figure."}


def _cand(value, publisher, cls, read="FULL_PAGE", basis="STATED", year="2025"):
    return {"value": value, "unit": None, "publisher": publisher,
            "source_url": f"https://example.test/{publisher.lower().replace(' ', '-')}",
            "as_of": year, "source_class": cls, "how_read": read,
            "figure_basis": basis, "excerpt": None, "note": None}


def _q(label, value, unit, country=None, mbps=None, candidates=None):
    return {"label": label, "value": value, "unit": unit, "country": country,
            "bandwidth_mbps": mbps, "as_of": "2024-12-31",
            "candidates": candidates or []}


DOMAINS = {
    1: ("Company and industry profile", "LLM-01",
        [_q("EMPLOYEES", "9052", "people", "DE")],
        [_src("Annual Report 2025", "PRIMARY_FILING"),
         _src("Handelsregister", "REGULATOR")]),
    2: ("Location footprint", "LLM-01",
        [_q("STORE", "371", "sites", "DE", candidates=[
            _cand("341", "Restructuring record", "REGULATOR", year="2021"),
            _cand("400", "Boersen-Zeitung", "TRADE_PRESS", year="2021"),
            _cand("371", "Fair Finance Guide", "AGGREGATOR", year="2023")]),
         _q("LARGE_OFFICE", "8", "sites", "DE")],
        [_src("Annual Report 2025", "PRIMARY_FILING"),
         _src("Fair Finance Guide", "AGGREGATOR", year="2023")]),
    6: ("Data-centre and cloud footprint", "LLM-01",
        [_q("DC", "2", "sites", "DE")],
        [_src("Company IR page", "COMPANY_PUBLISHED")]),
    7: ("Current architecture hypothesis", "LLM-01",
        [], [_src("Vendor case study", "OTHER", read="SNIPPET_ONLY")]),
    8: ("Current vendor and product signals", "LLM-01",
        [_q("BRANCH", "MPLS", "primary access")],
        [_src("Press release", "COMPANY_PUBLISHED")]),
    9: ("Public cost evidence", "LLM-08",
        [_q("TELECOM_SPEND", "213000000", "EUR/year", "DE")],
        [_src("Annual Report 2025", "PRIMARY_FILING")]),
    10: ("IT spend proxy", "LLM-08",
         [_q("IT_SERVICES_SPEND", "912000000", "EUR/year", "DE")],
         [_src("Annual Report 2025", "PRIMARY_FILING")]),
    12: ("Transformation announcements", "LLM-01",
         [_q("ANNOUNCED_SAVINGS", "40000000", "EUR/year", "DE")],
         [_src("Capital markets day", "COMPANY_PUBLISHED"),
          _src("Reuters", "TRADE_PRESS")]),
    13: ("Contract and sourcing events", "LLM-01", [],
         [_src("Reuters", "TRADE_PRESS", read="SNIPPET_ONLY")]),
    14: ("Resilience assumptions", "LLM-01",
         [_q("BRANCH", "0.6", "dual access share")],
         [_src("Annual Report 2025", "PRIMARY_FILING")]),
    15: ("Remote-user population", "LLM-01",
         [_q("BRANCH", "25", "users per site")],
         [_src("Sustainability report", "COMPANY_PUBLISHED")]),
    16: ("Operating-model cost", "LLM-01",
         [_q("OPS_COST", "900", "EUR/site/year", "DE")],
         [_src("Annual Report 2025", "PRIMARY_FILING")]),
    18: ("Market serviceability", "LLM-08", [],
         [_src("Bundesnetzagentur", "REGULATOR")]),
    19: ("Unit price evidence", "LLM-08",
         [_q("DIA 100Mbps MRC", "477.50", "EUR/month", "DE", mbps=100,
             candidates=[
                 _cand("450.00", "Bundesnetzagentur", "REGULATOR"),
                 _cand("505.00", "Carrier tariff", "COMPANY_PUBLISHED")])],
         [_src("Bundesnetzagentur", "REGULATOR"),
          _src("Carrier tariff", "COMPANY_PUBLISHED")]),
    20: ("Transformation cost benchmarks", "LLM-08",
         [_q("MIGRATION_COST", "1200", "EUR/site", "DE")],
         [_src("Sector study", "AGGREGATOR", read="SNIPPET_ONLY",
               basis="INFERRED")]),
    21: ("Currency and tax parameters", "LLM-08",
         [_q("VAT_RATE", "0.19", "share", "DE")],
         [_src("Bundeszentralamt fuer Steuern", "REGULATOR")]),
    22: ("Contract norms", "LLM-08", [],
         [_src("Sector study", "AGGREGATOR", read="SNIPPET_ONLY")]),
}


def main() -> int:
    print(f"{'#':>3}  {'domain':34} {'schema':8} {'grade':14} "
          f"{'disposition':18} routing")
    print("-" * 104)
    failures = []

    for no, (name, agent, quantities, sources) in sorted(DOMAINS.items()):
        reply = {
            "found": bool(quantities or sources),
            "subject": "Adolf Wuerth GmbH & Co. KG",
            "finding": f"Findings for {name}.",
            "quantities": quantities, "sources": sources,
            "confidence_note": None, "abstention_reason": None,
        }

        try:
            validate("PublicEvidenceResult", reply)
            schema = "OK"
        except Invalid as exc:
            failures.append(f"{no}. {name}: {exc}")
            print(f"{no:>3}  {name:34} {'REJECT':8} {'-':14} {'-':18} -")
            continue

        banded = TRI["triangulate"](quantities, policy=POLICY, price_year=2026)
        graded = REL["grade"](
            verified_sources=sources, claimed_sources=len(sources),
            band=banded[0] if banded else None, policy=POLICY,
            price_year=2026,
            value_parsed=bool([q for q in quantities
                               if TRI["parse_value"](q["value"]) is not None]))
        disposition, reason = REL["disposition_for"](graded["grade"])
        routing = sorted({_classify(q) for q in quantities}) or ["-"]

        blob = {"sources": sources, "quantities": quantities,
                "triangulated": banded,
                "conflicts": TRI["review_queue"](banded),
                "reliability": graded}
        try:
            json.dumps(blob)
        except TypeError as exc:
            failures.append(f"{no}. {name}: evidence blob not storable: {exc}")
            schema = "OK/JSON!"

        print(f"{no:>3}  {name:34} {schema:8} {graded['grade']:14} "
              f"{disposition:18} {','.join(routing)}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print("  -", f)
        return 1
    print(f"All {len(DOMAINS)} agent-routed domains validate, grade, store and "
          f"route.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
