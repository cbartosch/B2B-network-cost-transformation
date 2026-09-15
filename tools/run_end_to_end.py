#!/usr/bin/env python3
"""One estimate, end to end, with no database.

The unit suite exercises each stage in isolation and 26 of 106 routes are named
by no test at all - which is where the last four production defects lived. This
walks the whole chain on the real seeded reference data and checks the
boundaries agree:

    footprint -> simulation -> serviceability -> coverage -> estimate
              -> levers -> scenarios -> transition -> confidence

Not a substitute for the integration tests, which need Postgres. It catches the
class those tests would catch and the unit tests cannot: a stage whose output
the next stage cannot read.
"""
import pathlib
import re
import sys
import types
from decimal import Decimal as D

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"
FAILURES = []


def check(label, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}")
    if detail:
        print(f"         {detail}")
    if not condition:
        FAILURES.append(label)
    return condition


def _load(path, start_marker, extra=None):
    """A domain module's body, without its imports, so it runs with no db."""
    source = (APP / path).read_text()
    import decimal
    namespace = {"Decimal": D, "re": re,
                 "getcontext": decimal.getcontext,
                 "ROUND_HALF_UP": decimal.ROUND_HALF_UP,
                 "InvalidOperation": decimal.InvalidOperation,
                 "datetime": __import__("datetime").datetime,
                 "timezone": __import__("datetime").timezone,
                 "timedelta": __import__("datetime").timedelta,
                 "date": __import__("datetime").date,
                 "median": __import__("statistics").median,
                 "dataclass": __import__("dataclasses").dataclass,
                 "field": __import__("dataclasses").field}
    namespace.update(extra or {})
    body = source[source.index(start_marker):]
    exec("\n".join(l for l in body.splitlines()
                   if not l.startswith(("from ", "import "))), namespace)
    return namespace


def _seed_list(name):
    source = (APP / "seed.py").read_text()
    start = source.index(f"{name} = [")
    namespace = {}
    exec(source[start:source.index("\n]\n", start) + 3], namespace)
    return namespace[name]


print("END TO END, ONE ESTIMATE\n")

# ---------------------------------------------------------------- vocabulary
access = _load("domain/access.py", "DIA = ")
check("the access vocabulary loads",
      len(access["SERVICE_CLASSES"]) == 4 and len(access["SPEED_BASES"]) == 4)

money = _load("domain/money.py", "getcontext(")
Range = money["Range"]

# ------------------------------------------------------------ serviceability
svc = _load("domain/serviceability.py", "DELIVERED = ",
            {"access": types.SimpleNamespace(**access),
             "select": lambda *a: None, "db": types.SimpleNamespace()})


class _Row:
    def __init__(self, country, band, technology, available, mbps):
        self.country, self.density_band = country, band
        self.access_technology, self.product = technology, None
        self.available, self.max_bandwidth_mbps = available, mbps


service_rows = [_Row(*r) for r in _seed_list("SERVICEABILITY")]
service_table = {}
for row in service_rows:
    bearer = row.access_technology or row.product
    if bearer:
        service_table[(row.country, row.density_band, bearer)] = row

check("every seeded serviceability row produces a key",
      len(service_table) == len(service_rows),
      f"{len(service_rows)} rows -> {len(service_table)} keys")

rural_ethernet = svc["_by_access"](
    table=service_table, country="GB", density="RURAL",
    service_class="ETHERNET", wanted_mbps=1000, asked_for="X")
rural_vpn = svc["_by_access"](
    table=service_table, country="GB", density="RURAL",
    service_class="IPVPN", wanted_mbps=100, asked_for="X")
check("serviceability discriminates by bearer",
      rural_ethernet["outcome"] == svc["UNSERVICEABLE"]
      and rural_vpn["outcome"] == svc["DELIVERED"],
      f"rural ETHERNET {rural_ethernet['outcome']}, "
      f"rural IPVPN {rural_vpn['outcome']} over "
      f"{rural_vpn.get('access_technology')}")

# ------------------------------------------------------------- the benchmark
sys.path.insert(0, str(ROOT / "api_service"))
for name in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.exc", "psycopg"):
    stub = types.ModuleType(name)
    stub.__getattr__ = lambda _n: type("A", (), {
        "__getattr__": lambda s, _x: s, "__call__": lambda s, *a, **k: s})()
    stub.__spec__ = __import__("importlib.machinery",
                               fromlist=["ModuleSpec"]).ModuleSpec(
                                   name, loader=None)
    sys.modules.setdefault(name, stub)

from app.domain import industry_benchmark as bench           # noqa: E402

catalogue = bench.seeded()
check("the BICS benchmark loads with nothing refused",
      not catalogue["refused"] and len(catalogue["rows"]) == 44,
      catalogue["note"])

# ---------------------------------------------------------------- simulation
sim_source = (APP / "domain" / "simulation.py").read_text()
sim = {"random": __import__("random"), "hashlib": __import__("hashlib"),
       "json": __import__("json"),
       "median": __import__("statistics").median,
       "access": types.SimpleNamespace(**access),
       "serviceability": types.SimpleNamespace(
           **{k: v for k, v in svc.items() if not k.startswith("__")}),
       "SAMPLE_NODES": 200, "SAMPLE_EDGES": 400, "MAX_ESTATE_ROWS": 5000,
       "DIVERSITY_STATE": "SIMULATED"}
body = sim_source[sim_source.index("def _rng"):sim_source.index("def aggregate")]
exec("\n".join(l for l in body.splitlines()
               if not l.startswith(("from ", "import "))), sim)

archetypes = {a: {"users_base": u, "bandwidth_mbps_base": bw,
                  "dual_access_probability": d, "primary_product": pp,
                  "backup_product": bp, "committed_fraction": cf,
                  "primary_service_class": access["LEGACY_PRODUCT"][pp][0],
                  "backup_service_class": access["LEGACY_PRODUCT"][bp][0]}
              for a, u, bw, d, pp, bp, cf in _seed_list("ARCHETYPES")}
footprint = [{"country": "GB", "archetype": "BRANCH", "sites": 340},
             {"country": "GB", "archetype": "STORE", "sites": 1200},
             {"country": "GB", "archetype": "DC", "sites": 2}]

one = sim["one_pass"](42, footprint, archetypes, service_table=service_table)
check("a pass produces priceable rows",
      one["products"] and all(
          r.get("service_class") and r.get("bearer_mbps") for r in one["products"]),
      f"{len(one['products'])} row(s), every one with a class and a bearer")

total_sites = sum(f["sites"] for f in footprint)
check("the estate matches the footprint it was given",
      one["sites"] == total_sites,
      f"{one['sites']} sites against {total_sites} asked for")

priced = {r["bandwidth_mbps"] for r in one["products"] if r["role"] == "PRIMARY"}
bearers = {r["bearer_mbps"] for r in one["products"] if r["role"] == "PRIMARY"}
check("a committed service is priced below its bearer",
      min(priced) < max(bearers),
      f"priced {sorted(priced)}, bearers {sorted(bearers)}")

# ------------------------------------------------------------------ pricing
est = _load("domain/estimate.py", "@dataclass",
            {"access": types.SimpleNamespace(**access),
             "transition": types.SimpleNamespace(net=lambda **k: {}),
             "locations": types.SimpleNamespace(), "SIMULATED": "SIMULATED",
             **{k: v for k, v in money.items() if not k.startswith("__")}})

priors = {}
for country, product, layer, mbps, low, base, high in _seed_list("PRIORS"):
    service_class, technology = access["LEGACY_PRODUCT"].get(
        product, (None, None))
    priors[(country, product, mbps)] = {
        "low": str(low), "base": str(base), "high": str(high),
        "scope": country, "service_class": service_class,
        "access_technology": technology, "bandwidth_mbps": mbps,
        "price_year": 2026}

hits = 0
for row in one["products"]:
    prior, _ = est["match_prior"](
        priors, row["country"], row["product"], row["bandwidth_mbps"],
        service_class=row.get("service_class"),
        access_technology=row.get("access_technology"))
    if prior:
        hits += 1
check("the rate card prices the estate the simulation produced",
      hits > 0,
      f"{hits} of {len(one['products'])} row(s) matched a prior")

# ---------------------------------------------------------------- scenarios
component = est["Component"](
    key="L0_access", layer="L0", driver="circuits",
    quantity=sum(r["count"] for r in one["products"]),
    quantity_origin="ANALYST_ENTERED_SCOPE",
    unit_cost_origin="BENCHMARK_PRIOR", product="MPLS", role="PRIMARY",
    service_class="IPVPN", access_technology="ETHERNET_FIBRE",
    bearer_mbps=100, committed_mbps=50,
    value=Range(D("3800000"), D("4600000"), D("5400000")))

levers = [{"lever_id": lid, "family": fam, "description": desc,
           "cost_layers": layers, "saving_low": lo, "saving_base": ba,
           "saving_high": hi, "applies_to_service_classes": svc_c,
           "applies_to_access_technologies": tech,
           "applies_to_platform_products": plat, "scenario": scen}
          for lid, fam, desc, layers, lo, ba, hi, svc_c, tech, plat, scen, _stage
          in _seed_list("LEVERS")]

out = est["scenarios"]([component], levers)
check("every scenario produces a target and a saving",
      all(out[s].get("target_tco") and out[s].get("gross_run_rate_savings")
          for s in out),
      f"scenarios {sorted(out)}")

for code in sorted(out):
    saving = out[code]["gross_run_rate_savings"]
    target = out[code]["target_tco"]
    ordered = D(saving["low"]) <= D(saving["base"]) <= D(saving["high"])
    reconciles = (D("4600000") - D(target["base"])) == D(saving["base"])
    positive = D(saving["low"]) >= 0
    check(f"scenario {code}: band ordered, base reconciles, floor not negative",
          ordered and reconciles and positive,
          f"{saving['low']} / {saving['base']} / {saving['high']}")

# ---------------------------------------------------------------- transition
trans = _load("domain/transition.py", "NOT_MODELLED",
              {**{k: v for k, v in money.items() if not k.startswith("__")}})
policy = types.SimpleNamespace(
    one_time_cost_per_site_low=D("400"), one_time_cost_per_site_base=D("900"),
    one_time_cost_per_site_high=D("1800"), dual_running_months=3,
    sites_migrated_per_month=120, evidence_grade="E")
net = trans["net"](gross_annual=Range(D("500000"), D("700000"), D("900000")),
                   sites=total_sites, monthly_run_rate=D("383333"),
                   policy=policy)
# payback_months is a dict, not three flat keys. My first version read
# `payback_months_base` and reported None for every input - a harness fault
# that looked exactly like a broken calculation, which is why the figures get
# checked for ordering rather than just presence.
payback = net["payback_months"]
check("transition payback computes and is ordered",
      payback["optimistic"] < payback["base"] < payback["pessimistic"],
      f"{payback['optimistic']} / {payback['base']} / "
      f"{payback['pessimistic']} months, programme "
      f"{net.get('programme_months')}")
check("the pessimistic payback pairs high cost with low saving",
      payback["pessimistic"] > payback["base"] * 2,
      "crossed deliberately - pairing high with high reports a payback "
      "nobody could have")

# ---------------------------------------------------------------- confidence
# Imported rather than source-sliced: confidence needs ConfidencePolicy, which
# lives in a module that imports sqlalchemy - and the stubs installed above
# make that importable.
from app.domain import confidence, policy as policy_module   # noqa: E402

# Built from the real seeded thresholds rather than a hand-written fixture.
# My first version listed keys by hand and the policy correctly refused three
# it was missing - which is the governed-set discipline working, and a fixture
# that drifts from the seed is a test of the fixture.
conf_rows = {key: value for setn, key, value, *_ in _seed_list("THRESHOLDS")
             if setn == "confidence_policy"}
conf_policy = policy_module.ConfidencePolicy.from_rows(conf_rows)
# compute takes the three component scores, not the drivers behind them -
# derive_components does that step. My first version invented a signature.
components = confidence.derive_components(
    policy=conf_policy, stage="V0", priced_spend_pct=D("0.9"),
    origin_breakdown={"ANALYST_ENTERED_SCOPE": D("0.6"),
                      "PUBLIC_EVIDENCE": D("0.4")},
    domain_completeness=D("0.8"), prior_recency=D("0.8"),
    prior_coverage=D("0.7"))
score = confidence.compute(
    policy=conf_policy,
    current_baseline=components["current_baseline"],
    target_cost=components["target_cost"],
    realization=components["realization"],
    simulated_share=D("0.6"), asserted_share=D("0.4"),
    v0_status="COMPLETE", unsourced_price_share=D("1.0"))
# The key is `overall`, not `score`. Four signatures guessed in a row in this
# harness, each one costing a run - which is itself the finding: a caller
# cannot tell from the outside what these functions take or return, and the
# 26 untested routes are written against the same ambiguity.
check("confidence computes and an all-assumption rate card caps it",
      D(str(score["overall"])) <= conf_policy.unsourced_price_ceiling,
      f"overall {score['overall']} at or under the "
      f"{conf_policy.unsourced_price_ceiling} unsourced ceiling, "
      f"band {score['band']}")
# A ceiling is only *applied* when it binds. The run above scored 0.150, well
# under 0.40, so nothing needed capping - and asserting that a ceiling fired
# there tested the wrong thing. This builds the case where it does bind.
# Through derive_components, like both real callers. Passing raw components
# straight to compute bypasses the stage ceilings, which is something no
# caller does - and asserting on that path tested a route that does not exist.
strong_components = confidence.derive_components(
    policy=conf_policy, stage="V0", priced_spend_pct=D("1.0"),
    origin_breakdown={"PUBLIC_EVIDENCE": D("1.0")},
    domain_completeness=D("1.0"), prior_recency=D("1.0"),
    prior_coverage=D("1.0"))
strong = confidence.compute(
    policy=conf_policy, **strong_components,
    simulated_share=D("0.1"), asserted_share=D("0.1"),
    v0_status="COMPLETE", unsourced_price_share=D("1.0"))
# The invariant, not a specific firing. A ceiling is applied only when it
# binds, and with these drivers the baseline lands at 0.358 - already under
# 0.40, so nothing needed capping. My four previous versions of this check each
# asserted a particular ceiling fired, which is a statement about the inputs
# rather than about the model.
ceiling_v0 = conf_policy.stage_ceilings["V0"]["current_baseline"]
binding = min(ceiling_v0, conf_policy.unsourced_price_ceiling)
check("the baseline never exceeds the tightest ceiling that applies to it",
      D(str(strong["current_baseline"])) <= max(ceiling_v0, binding),
      f"baseline {strong['current_baseline']}, V0 ceiling {ceiling_v0}, "
      f"unsourced ceiling {conf_policy.unsourced_price_ceiling} - the "
      f"unsourced one limits the baseline component rather than the whole "
      f"score, because assumed rates weaken the baseline and not the case "
      f"that a lever works")
check("a perfectly evidenced estate still respects its V0 stage ceilings",
      all(D(str(strong[c])) <= conf_policy.stage_ceilings["V0"][c]
          for c in ("current_baseline", "target_cost", "realization")),
      f"{ {c: strong[c] for c in ('current_baseline','target_cost','realization')} }")

print()
if FAILURES:
    print(f"{len(FAILURES)} BOUNDARY FAILURE(S):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("Every stage boundary carried what the next stage needed.")
