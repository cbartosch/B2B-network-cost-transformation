#!/usr/bin/env python3
"""Which parts of an estimate change with the client, and which never do?

An outside-in V0 is meant to be partly generic: a market rate is a market rate
and a lever is a lever. But a figure that should vary by client and does not is
a generic estimate wearing a company's name, and the caller cannot tell the
difference by looking at the output.

This reports, for every input the estimate consumes, whether it is scoped to
the case, to a governed reference set, or hardcoded.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"

DB = (APP / "db.py").read_text()
API = (APP / "routers" / "api.py").read_text()


def _columns(table):
    start = DB.index(f"{table} = Table(")
    end = DB.index("schema=", start)
    return set(re.findall(r'Column\("(\w+)"', DB[start:end]))


def _tables():
    return re.findall(r"^(\w+) = Table\(", DB, re.M)


print("WHAT VARIES BY CLIENT\n")

# ------------------------------------------------- 1. tables, by scope
print("1. reference tables the estimate reads: are they case-scoped?")
print("-" * 62)
CONSUMED = [
    ("unit_cost_prior", "the market rate card - what a circuit costs"),
    ("case_rate", "what THIS client pays - tried before the market card"),
    ("platform_unit_cost", "SD-WAN and SSE licence cost"),
    ("lever", "what each saving lever is worth"),
    ("archetype_prior", "users, bandwidth and dual access per site type"),
    ("archetype_bandwidth", "bandwidth per industry and site type"),
    ("density_mix", "how a site total splits across density bands"),
    ("serviceability", "what can be delivered where"),
    ("industry_benchmark", "published bandwidth, CIR and criticality"),
    ("threshold", "every governed policy value"),
    ("topology_template", "the target architecture"),
    ("country_region", "which region a country sits in"),
]
generic = []
for table, what in CONSUMED:
    if table not in _tables():
        print(f"  {table:22} ABSENT")
        continue
    scoped = "case_id" in _columns(table)
    mark = "case" if scoped else "GLOBAL"
    if not scoped:
        generic.append((table, what))
    print(f"  [{mark:6}] {table:22} {what}")

print(f"\n  {len(generic)} of {len(CONSUMED)} are the same for every client.")

# --------------------------------------- 2. what IS case-scoped
print("\n2. what the case supplies")
print("-" * 62)
case_columns = sorted(_columns("case"))
SUPPLIES = [c for c in case_columns
            if c not in ("case_id", "created_at", "created_by", "updated_at")]
print(f"  {len(SUPPLIES)} fields on the case:")
for chunk in range(0, len(SUPPLIES), 3):
    print("    " + "  ".join(f"{c:28}" for c in SUPPLIES[chunk:chunk + 3]))

# --------------------------------- 3. the case-scoped evidence tables
print("\n3. case-scoped evidence")
print("-" * 62)
scoped = sorted(t for t in _tables() if "case_id" in _columns(t))
print(f"  {len(scoped)} tables carry a case_id:")
for chunk in range(0, len(scoped), 3):
    print("    " + "  ".join(f"{t:26}" for t in scoped[chunk:chunk + 3]))

# ----------------------------- 4. can a client override a global figure?
print("\n4. where a client can override a governed figure")
print("-" * 62)
OVERRIDES = [
    ("service class per site type", "service_class_by_archetype"),
    ("committed fraction per site type", "committed_fraction_by_archetype"),
    ("which total to use as the footprint", "footprint_total_choice"),
    ("the rate card", "case_rate"),
    ("lever saving bands", None),
    ("transition cost per site", None),
    ("serviceability", None),
]
for label, column in OVERRIDES:
    # A case override is either a column on the case or a case-scoped table.
    if column and (column in _columns("case")
                   or (column in _tables() and "case_id" in _columns(column))):
        print(f"  [yes   ] {label}")
    else:
        print(f"  [NO    ] {label}")

print("\nA global figure is right where the market sets it and wrong where the")
print("client does. The second list is the one to judge.")
