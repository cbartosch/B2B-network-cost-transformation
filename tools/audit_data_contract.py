#!/usr/bin/env python3
"""Section C of the audit mandate: the input data contract, field by field.

Every numeric field that reaches a calculation needs three things a reader can
find: what it counts, over what period, and in what currency. A field missing
any of them is a silent unit error waiting to happen, and this system has
already had one - the ops cost is annual per site while every circuit price is
monthly, and the distinction lived in a page label. A monthly figure typed
there understated total cost by 42% on a 2,000-site estate and produced a
number that looked entirely plausible.

`make audit-contract`, exit code non-zero when a money or rate field carries no
period.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
UI = ROOT / "analyst_ui" / "streamlit_app"

# A field whose name or type says it holds money, or a rate, or a count.
MONEY = re.compile(r"cost|spend|price|value|charge|savings|revenue|budget|"
                   r"anchor|tco|rate", re.I)
# A year is not a price. `price_year` and `as_of_year` set the price basis and
# carry no period of their own - matching them made the tool report seven high
# findings of which three were the word "price" inside "price_year", and a
# check that cries wolf gets ignored rather than fixed.
NOT_MONEY = re.compile(r"_year$|^year$|_no$|_id$|_version$|_months?$", re.I)
PERIOD = re.compile(r"per_year|annual|per_month|monthly|per_site_per|_pa\b|"
                    r"yearly|per_day", re.I)
COUNT = re.compile(r"sites|users|circuits|count|_no$|employees|locations", re.I)
CURRENCY_FIELD = re.compile(r"currency|_ccy$", re.I)


def _request_models() -> dict:
    """Every Pydantic request model in the API, with its annotated fields."""
    api = (APP / "routers" / "api.py").read_text()
    models = {}
    for node in ast.parse(api).body:
        if not (isinstance(node, ast.ClassDef)
                and any(getattr(b, "id", "") == "BaseModel"
                        for b in node.bases)):
            continue
        fields = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target,
                                                              ast.Name):
                fields[item.target.id] = ast.unparse(item.annotation)
        if fields:
            models[node.name] = fields
    return models


def _numeric(annotation: str) -> bool:
    return bool(re.search(r"\b(int|float|Decimal)\b", annotation))


def audit() -> list:
    findings = []
    models = _request_models()
    api = (APP / "routers" / "api.py").read_text()
    ui = "\n".join(p.read_text() for p in UI.rglob("*.py"))

    for model, fields in sorted(models.items()):
        has_currency = any(CURRENCY_FIELD.search(f) for f in fields)
        for field, annotation in sorted(fields.items()):
            if not _numeric(annotation):
                continue
            money = bool(MONEY.search(field)) and not NOT_MONEY.search(field)
            count = bool(COUNT.search(field))
            period = bool(PERIOD.search(field))

            # A money field with no period in its name is the ops-cost defect.
            # A sibling `unit` field declares the period for a generic value:
            # KnownFactIn.value_base is whatever `unit` says it is, which is
            # the design. The weakness there is that `unit` is free text, not
            # that the period is undeclared - a different finding, and one the
            # split_unit work already addresses.
            unit_declared = any(f == "unit" or f.endswith("_unit")
                                for f in fields)
            if money and not count and not period and not unit_declared:
                # Does anything else declare it? A unit sibling, or a label.
                labelled = bool(re.search(
                    rf"{field}.{{0,200}}(per year|per month|annual|monthly)",
                    api + ui, re.I | re.S))
                findings.append({
                    "severity": "HIGH" if not labelled else "MEDIUM",
                    "model": model, "field": field, "type": annotation,
                    "issue": ("money or rate field with no period in its name"
                              + ("; a nearby label states one, which is not a "
                                 "contract" if labelled
                                 else "; no period stated anywhere")),
                })
            if money and not count and not has_currency:
                findings.append({
                    "severity": "MEDIUM", "model": model, "field": field,
                    "type": annotation,
                    "issue": "money field in a model with no currency field",
                })
    return findings


def currency_reconciliation() -> list:
    """Is the estimate's currency reconciled anywhere between its inputs?

    Every seeded price prior is hardcoded USD. A case declares base_currency
    (defaulting to USD) and an fx_convention, which pre-flight requires to be
    present and no calculation reads. The anchor is a bare Decimal with no
    currency at all.

    So a GBP or EUR anchor entered against USD priors is arithmetic on mixed
    units, and the snapshot then labels the result with the case's
    base_currency - asserting a currency the calculation never established. On
    a EUR 213M anchor read as USD that is a 7.4% understatement; on GBP,
    21.3%.

    Reported, not fixed: which currency the model works in, and whether it
    converts or refuses, is a decision for whoever owns the cost model.
    """
    blob = "\n".join(p.read_text() for p in APP.rglob("*.py"))
    gaps = []
    for label, pattern in (
            ("no FX rate table exists", r"fx_rate|exchange_rate"),
            ("no conversion function exists", r"def convert|to_base_currency"),
            ("priors are not filtered by currency", r"c\.currency\s*=="),
            ("the anchor carries no currency", r"anchor_currency"),
            ("no mixed-currency refusal", r"MIXED_CURRENCY")):
        if not re.search(pattern, blob, re.I):
            gaps.append({"severity": "HIGH", "model": "estimate",
                         "field": "currency", "type": "-", "issue": label})
    return gaps


def main() -> int:
    findings = audit() + currency_reconciliation()
    high = [f for f in findings if f["severity"] == "HIGH"]
    print(f"{len(findings)} data-contract finding(s), {len(high)} high\n")
    for f in sorted(findings, key=lambda x: (x["severity"], x["model"])):
        print(f"  [{f['severity']:6}] {f['model']}.{f['field']} "
              f"({f['type']})")
        print(f"            {f['issue']}")
    if high:
        print("\nA money or rate field with no period is a silent unit error: "
              "the ops cost understated total cost by 42% that way.")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main())
