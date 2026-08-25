import pandas as pd
import streamlit as st
import api_client as api

st.title("6. Run V0")
st.caption("Specification 0.3C - the coverage gate decides COMPLETE, PARTIAL or refused.")

case_id = st.session_state.get("case_id")
# Session state outlives a case switch, so anything cached here must be scoped
# to the case it came from or it will be rendered under the wrong one.
_scope = st.session_state.get("_scoped_case")
if _scope != case_id:
    for _k in ['v0']:
        st.session_state.pop(_k, None)
    st.session_state["_scoped_case"] = case_id
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

sims = api.get(f"/v1/outside-in/cases/{case_id}/simulations").get("runs", [])
if not sims:
    st.warning("Run a simulation first - V0 quantities derive from it."); st.stop()

pick = st.selectbox("Simulation run",
                    [f"{s['simulation_run_id'][:8]} - seed {s['seed']} x{s['ensemble_size']}"
                     for s in sims])
sim_id = sims[[f"{s['simulation_run_id'][:8]} - seed {s['seed']} x{s['ensemble_size']}"
               for s in sims].index(pick)]["simulation_run_id"]

case = api.get(f"/v1/outside-in/cases/{case_id}")
countries = case.get("in_scope_countries") or ["GB", "DE", "US"]
st.subheader("Declared spend by country (cross-check only)")
st.caption("The coverage denominator is derived from the simulated scope and the approved "
           "priors. Anything entered here is reconciled against that and reported - it "
           "cannot move the gate.")
spend_df = st.data_editor(
    pd.DataFrame([{"country": c, "estimated_annual_spend": 1_000_000} for c in countries]),
    num_rows="dynamic", use_container_width=True)

c1, c2 = st.columns(2)
users = c1.number_input("Remote/office users", 100, 500_000, 5_000)
ops = c2.number_input("Ops cost per site per year", 0.0, 100_000.0, 900.0)

st.subheader("Quantity provenance")
st.caption("A quantity is either your typed scope or a registered known fact. Naming the "
           "fact is the only way to claim the latter, so the link is traceable. A "
           "corroborated fact enters as public evidence and raises the baseline; an "
           "uncorroborated one is an assertion and triggers the 0.6A ceiling.")

src = api.get(f"/v1/outside-in/cases/{case_id}/quantity-sources")
if "_error" in src:
    src = {"footprint": [], "users": []}


def _picker(label, driver, column):
    options = [f for f in src.get(driver, []) if f["eligible"]]
    if not options:
        column.caption(f"**{label}:** typed scope — no eligible known fact registered.")
        return None
    labels = {"Typed scope (analyst-entered)": None}
    for f in options:
        tag = "corroborated" if f["corroboration_state"] == "CORROBORATED" else "asserted"
        labels[f"{f['subject']} — {f['value_base']} ({f['asserted_by']}, {tag})"] = \
            f["known_fact_id"]
    choice = column.selectbox(label, list(labels))
    picked = labels[choice]
    if picked:
        f = next(x for x in options if x["known_fact_id"] == picked)
        column.caption(f"Enters as **{f['would_carry_origin']}**.")
    return picked


c3, c4 = st.columns(2)
fp_fact = _picker("Footprint source", "footprint", c3)
us_fact = _picker("User-count source", "users", c4)

if st.button("Run V0 estimate", type="primary"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/estimates:run", {
        "simulation_run_id": sim_id, "users": int(users),
        "ops_cost_per_site_base": float(ops),
        "footprint_known_fact_id": fp_fact, "users_known_fact_id": us_fact,
        # Reconciled and reported, never the coverage denominator.
        "declared_spend_by_country": {r["country"]: r["estimated_annual_spend"]
                                      for r in spend_df.to_dict("records")}})
    st.session_state["v0"] = r

v0 = st.session_state.get("v0")
if not v0:
    st.stop()
if "_error" in v0:
    e = v0["_error"]
    st.error("**V0 did not publish.**")
    st.json(e if isinstance(e, dict) else {"detail": e})
    st.stop()

cov, conf = v0["coverage"], v0["confidence"]
if v0["v0_status"] == "PARTIAL":
    st.warning(f"**V0 PARTIAL** - effective coverage {cov['effective_coverage_pct']}. "
               f"{cov['reason']}")
    if cov["unpriced_countries"]:
        st.error(f"Unpriced and **excluded from the headline, not valued at zero**: "
                 f"{', '.join(cov['unpriced_countries'])}")
    if cov.get("unsizable_pairs"):
        st.error(f"**Cannot be sized at any approved rate** "
                 f"({cov.get('unsizable_circuits', 0)} circuits): "
                 f"{', '.join(cov['unsizable_pairs'])}. Their value is unknown, "
                 f"not zero, so coverage is governed by circuit count here.")
else:
    st.success("**V0 COMPLETE** - all coverage tests passed.")

a, b, c, d = st.columns(4)
a.metric("Current TCO (base)", f"{float(v0['current_tco']['base']):,.0f}")
b.metric("Overall confidence", conf["overall"], conf["band"])
c.metric("Simulated share", f"{float(v0['simulated_share']):.0%}")
d.metric("Asserted share", f"{float(v0['asserted_share']):.0%}",
         f"typed scope {float(v0.get('entered_share', 0)):.0%}", delta_color="off")

if conf["ceilings_applied"]:
    st.info("**Confidence ceilings applied (0.6A):** " + "; ".join(conf["ceilings_applied"]))
else:
    st.caption("No confidence ceiling tripped - simulated share is below the 10% band.")

st.subheader("Where the simulated share comes from")
st.caption("Derived from the share of bill-of-materials value whose *quantity* was "
           "decided by the simulation. Unit prices come from approved reference priors "
           "in every case.")
kf = v0.get("known_facts") or {}
if kf.get("registered"):
    bound, info = len(kf.get("bound_to_a_driver") or []), len(kf.get("informational") or [])
    st.caption(f"Known facts: {kf['registered']} registered — {bound} supplying a "
               f"quantity, {info} informational. {kf.get('uncorroborated', 0)} "
               f"uncorroborated.")
    kfv = v0.get("known_fact_value") or {}
    if kfv:
        st.dataframe(pd.DataFrame([{"Known fact": k, "Value it accounts for": float(x)}
                                   for k, x in kfv.items()]),
                     use_container_width=True, hide_index=True)

ps1, ps2, ps3 = st.columns(3)
ps1.metric("Typed scope share", v0.get("entered_scope_share", "-"))
ps2.metric("Asserted share", v0.get("asserted_share", "-"), "registered facts",
           delta_color="off")
ps3.metric("Simulated share", v0.get("simulated_share", "-"))

cb1, cb2, cb3 = st.columns(3)
cb1.metric("Value coverage", cov.get("priced_spend_pct", "-"))
cb2.metric("Circuit coverage", cov.get("circuit_coverage_pct", "-"),
           f"{cov.get('priced_circuits', 0)}/{cov.get('total_circuits', 0)}",
           delta_color="off")
cb3.metric("Effective (governs)", cov.get("effective_coverage_pct", "-"),
           "worse of the two", delta_color="off")
st.caption("Value coverage can be defeated by scope that carries no approved rate in "
           "any country, because unsizable scope contributes nothing to a value "
           "denominator. Circuit coverage always counts it, so the worse of the two "
           "decides the gate.")

cc = (v0.get("coverage") or {}).get("declared_spend_crosscheck")
if cc:
    st.caption(f"Declared total {float(cc['declared_total']):,.0f} vs derived "
               f"{float(cc['derived_total']):,.0f} "
               f"(divergence {cc['divergence_pct']}).")
    if cc["countries_in_scope_but_not_declared"]:
        st.warning("In scope but not declared: "
                   + ", ".join(cc["countries_in_scope_but_not_declared"]))

ob = v0.get("origin_breakdown", {})
if ob:
    st.dataframe(pd.DataFrame([
        {"Quantity origin": k, "Value": float(v["value"]), "Share": f"{float(v['share']):.1%}"}
        for k, v in ob.items()]), use_container_width=True, hide_index=True)

by_scen = v0.get("simulated_share_by_scenario", {})
if by_scen:
    st.caption("Per scenario, computed on each target rather than on the baseline. "
               "A scenario that strips unsimulated layers leaves a proportionally "
               "more simulated target.")
    st.dataframe(pd.DataFrame([
        {"Scenario": k, "Simulated share of target": f"{float(v):.2%}"}
        for k, v in by_scen.items()]), use_container_width=True, hide_index=True)

comps = v0.get("components", [])
if comps:
    with st.expander("Component-level provenance"):
        st.dataframe(pd.DataFrame([
            {"Component": c["key"], "Layer": c["layer"], "Driver": c["driver"],
             "Quantity": c["quantity"], "Quantity origin": c["quantity_origin"],
             "Unit cost origin": c["unit_cost_origin"],
             "Value (base)": float(c["value"]["base"])} for c in comps]),
            use_container_width=True, hide_index=True)

unpriced = (v0.get("coverage") or {}).get("unpriced_components") or []
if unpriced:
    st.warning("**Unpriced components excluded from the total** (never valued at zero, "
               "never given a neighbouring country's rate):")
    st.dataframe(pd.DataFrame(unpriced), use_container_width=True, hide_index=True)

st.subheader("Scenarios")
rows = [{"Scenario": k, "Label": s["label"],
         "Target TCO (base)": float(s["target_tco"]["base"]),
         "Savings (base)": float(s["gross_run_rate_savings"]["base"]),
         "Savings %": s["savings_pct_base"],
         "Levers applied": len(s["levers"]),
         "Simulated share": f"{float(s['simulated_share']):.2%}"}
        for k, s in v0["scenarios"].items()]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with st.expander("Confidence detail and drivers"):
    st.caption("Components are derived from the run, not supplied as constants.")
    st.json(conf)
with st.expander("Coverage detail"):
    st.json(cov)
