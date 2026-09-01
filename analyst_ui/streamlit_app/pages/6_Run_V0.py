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
                     for s in sims], key="v0_pick")
sim_id = sims[[f"{s['simulation_run_id'][:8]} - seed {s['seed']} x{s['ensemble_size']}"
               for s in sims].index(pick)]["simulation_run_id"]

case = api.get(f"/v1/outside-in/cases/{case_id}")
_rs = case.get("run_settings") or {}
countries = case.get("in_scope_countries") or ["GB", "DE", "US"]
st.subheader("Declared spend by country (optional cross-check)")
st.caption("Only fill this in where the client has actually told you what they "
           "spend. It is reconciled against the derived total and reported; it "
           "cannot move the coverage gate. Leave it empty if you do not have "
           "the figures - an invented number produces an invented divergence.")

# Empty, not one million per country. The table used to open pre-filled with
# 1,000,000 for every in-scope country, which is not a placeholder anyone reads
# as one: it is the right order of magnitude for a real telecom spend, it feeds
# the declared-spend crosscheck, and it therefore produced a divergence figure
# computed against a number nobody supplied.
_saved_spend = case.get("declared_spend_by_country") or {}
spend_df = st.data_editor(
    pd.DataFrame(
        [{"country": c, "estimated_annual_spend": v}
         for c, v in sorted(_saved_spend.items())]
        or [{"country": "", "estimated_annual_spend": None}]),
    num_rows="dynamic", use_container_width=True,
    column_config={"estimated_annual_spend": st.column_config.NumberColumn(
        "estimated_annual_spend", help="Annual spend as the client stated it. "
                                       "Leave blank where they have not.")}, key="v0_spend_df")

c1, c2 = st.columns(2)
# Persisted on the case rather than defaulted every visit. 5,000 users and 900
# per site were invented figures that went straight into the baseline, and they
# had to be retyped on every visit - so whatever was there last time was
# whatever the defaults happened to be.
users = c1.number_input(
    "Remote/office users", 0, 500_000,
    int(case.get("declared_users") or 0),
    help="Zero until you have a figure. It drives the SSE licence line "
         "directly, so a guess here is a guess in the baseline.", key="v0_users")
ops = c2.number_input(
    "Ops cost per site per year", 0.0, 100_000.0,
    float(case.get("declared_ops_cost_per_site") or 0.0),
    help="Zero until you have a figure, rather than an assumed 900.", key="v0_ops")

if st.button("Save these inputs to the case"):
    _r = api.put(f"/v1/outside-in/cases/{case_id}", {
        "run_settings": {**(case.get("run_settings") or {}),
                         "method": method,
                         "anchor_value": float(anchor_value or 0.0)},
        "declared_users": int(users),
        "declared_ops_cost_per_site": float(ops),
        "declared_spend_by_country": {
            str(r["country"]).strip().upper(): float(r["estimated_annual_spend"])
            for r in spend_df.to_dict("records")
            if str(r.get("country") or "").strip()
            and r.get("estimated_annual_spend") not in (None, "")
            and r["estimated_annual_spend"] == r["estimated_annual_spend"]}})
    if "_error" in _r:
        st.error(_r["_error"])
    else:
        api.flash("Inputs saved to the case.")
        st.rerun()

if not users:
    st.warning("Users is zero, so the SSE licence line will be zero. That is "
               "correct until you have a figure - it is not a placeholder "
               "standing in for one.")

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
    choice = column.selectbox(label, list(labels), key="v0_choice")
    picked = labels[choice]
    if picked:
        f = next(x for x in options if x["known_fact_id"] == picked)
        column.caption(f"Enters as **{f['would_carry_origin']}**.")
    return picked


c3, c4 = st.columns(2)
fp_fact = _picker("Footprint source", "footprint", c3)
us_fact = _picker("User-count source", "users", c4)

st.divider()
st.subheader("Estimation method")
st.caption("BUILD_UP enumerates the estate and prices every circuit. ANCHOR "
           "starts from a disclosed spend line and a governed addressable "
           "share, for the normal outside-in case where no site-level circuit "
           "inventory is public. Both run through the same levers, the same "
           "confidence model and the same ceilings; neither is a fallback that "
           "fires on its own, because a method that switches itself produces a "
           "number whose basis nobody chose.")
# Read from the case. The method decides which question the estimate answers,
# and it was widget state - so switching page reverted an ANCHOR case to
# BUILD_UP and the next run priced an estate the analyst had deliberately
# chosen not to enumerate.
_methods = ["BUILD_UP", "ANCHOR"]
method = st.radio("Method", _methods, horizontal=True,
                  index=_methods.index(_rs.get("method"))
                  if _rs.get("method") in _methods else 0,
                  help="BUILD_UP needs a completed simulation. ANCHOR needs a "
                       "disclosed annual spend figure.", key="v0_method")

anchor_value, anchor_fact = None, None
if method == "ANCHOR":
    a1, a2 = st.columns(2)
    anchor_value = a1.number_input(
        "Disclosed annual spend (anchor)", min_value=0.0,
        value=float(_rs.get("anchor_value") or 0.0), step=1_000_000.0,
        help="The cost line the addressable pool is a share of - a "
             "telecommunication costs or IT services figure from the annual "
             "report. It is an upper bound: it carries voice, mobile and "
             "non-WAN services the transformation cannot touch.", key="v0_anchor_value")
    anchor_fact = _picker("Anchor source", "anchor_spend", a2)
    if not anchor_fact:
        a2.caption("Typed: the estimate will rest on an assertion and report "
                   "PARTIAL. Register the figure as a known fact and "
                   "corroborate it to lift that.")

if st.button("Run V0 estimate", type="primary"):
    payload = {"method": method, "users": int(users),
               "ops_cost_per_site_base": float(ops),
               "footprint_known_fact_id": fp_fact, "users_known_fact_id": us_fact,
               # Reconciled and reported, never the coverage denominator.
               # Only rows the analyst actually filled in. A blank row used to
               # arrive as {"": nan} and a pre-filled one as an invented
               # million, either of which produces a divergence against a
               # figure nobody supplied.
               "declared_spend_by_country": {
                   str(r["country"]).strip().upper(): float(r["estimated_annual_spend"])
                   for r in spend_df.to_dict("records")
                   if str(r.get("country") or "").strip()
                   and r.get("estimated_annual_spend") not in (None, "")
                   and r["estimated_annual_spend"] == r["estimated_annual_spend"]}}
    if method == "ANCHOR":
        payload.update({"anchor_value": anchor_value or None,
                        "anchor_known_fact_id": anchor_fact})
    else:
        payload["simulation_run_id"] = sim_id
    r = api.post(f"/v1/outside-in/cases/{case_id}/estimates:run", payload)
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

_method = v0.get("method", "BUILD_UP")
if _method == "ANCHOR":
    _b = v0.get("anchor_basis") or {}
    _pool = _b.get("addressable_pool") or {}
    _share = _b.get("addressable_share") or {}
    st.info(
        f"**Method: ANCHOR.** Anchored on a disclosed figure of "
        f"{float(_b.get('anchor_value', 0)):,.0f}, of which "
        f"{float(_share.get('low', 0)):.0%}-{float(_share.get('high', 0)):.0%} "
        f"is treated as addressable - a governed assumption, not an "
        f"observation. Addressable pool "
        f"{float(_pool.get('low', 0)):,.0f} to {float(_pool.get('high', 0)):,.0f}. "
        f"Anchor provenance: {_b.get('anchor_origin', 'unknown')}.")
    st.caption(_b.get("caveat", ""))

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

if _method == "ANCHOR":
    st.subheader("Why the simulated share is zero")
    st.caption("Nothing was enumerated, so no quantity was decided by a "
               "seeded draw. The uncertainty in this method sits in the "
               "addressable share above, not in a simulated topology - and "
               "the circuit coverage figure is zero for the same reason, "
               "which is not comparable with a BUILD_UP run.")
else:
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

# --------------------------------------------------------------- refinement
st.divider()
st.subheader("How this estimate has changed")
st.caption("The workflow is meant to produce an estimate that improves as "
           "evidence arrives. Confidence derives from priced coverage, the "
           "origin mix and domain completeness, so it does - but every "
           "snapshot used to be an island, and a re-run after promoting three "
           "sources gave a different number with no account of why.")

_prog = api.get(f"/v1/outside-in/cases/{case_id}/estimates:progression")
if "_error" in _prog:
    st.error(_prog["_error"])
elif len(_prog.get("snapshots") or []) < 2:
    st.info("One estimate so far, so there is nothing to compare it with. Run "
            "V0 again after promoting research or corroborating a fact and the "
            "movement will be attributed here.")
else:
    st.dataframe(pd.DataFrame([{
        "created": s_["created_at"][:19].replace("T", " "),
        "method": s_["method"], "status": s_["v0_status"],
        "confidence": s_["confidence"], "band": s_["band"],
        "coverage": s_["coverage"],
    } for s_ in _prog["snapshots"]]), use_container_width=True,
        hide_index=True)
    st.caption(f"{_prog['refinements']} of {len(_prog['steps'])} step(s) are "
               f"refinements - a figure moved and an improvement in the "
               f"evidence explains it.")

    for step in reversed(_prog["steps"]):
        _icon = "improved" if step["is_refinement"] else "changed"
        with st.expander(f"{step['to_created'][:19].replace('T', ' ')} - "
                         f"{_icon}", expanded=step is _prog["steps"][-1]):
            st.write(step["summary"])
            if step["moved"]:
                st.dataframe(pd.DataFrame([{
                    "field": m["field"], "from": m["from"], "to": m["to"],
                    "change": (f"{m['change_pct']:+.1%}"
                               if m.get("change_pct") is not None else ""),
                } for m in step["moved"]]), use_container_width=True,
                    hide_index=True)
            for cause in step["causes"]:
                (st.success if cause.get("improves") else st.info)(
                    cause["statement"])
            for gap in step["unexplained"]:
                st.warning(gap)

st.caption(_prog.get("note", "") if "_error" not in _prog else "")

# ------------------------------------------------------------- ask about it
st.divider()
st.subheader("Ask about this estimate")
st.caption("How was it calculated, why is confidence where it is, what would "
           "improve it. Answers are drawn from what the run recorded: an "
           "answer stating a figure the estimate does not contain is refused, "
           "and the gaps are computed from the run rather than composed.")

_q = st.text_input(
    "Question", key="v0_question",
    placeholder="Why is coverage 55% and what would raise it?")
_examples = [
    "How was the current cost calculated?",
    "Why is confidence band C rather than B?",
    "What is the single most valuable thing to research next?",
    "Which figures rest on an assertion rather than evidence?",
    "What would it take to move from V0 to a defensible V1?",
]
st.caption("Try: " + " · ".join(f"*{e}*" for e in _examples[:3]))

if st.button("Ask", disabled=not (_q or "").strip()):
    with st.spinner("Reading the estimate..."):
        st.session_state["_ask"] = api.post(
            f"/v1/outside-in/cases/{case_id}/estimates:ask",
            {"question": _q}, timeout=300.0)

_ans = st.session_state.get("_ask")
if _ans and "_error" in _ans:
    st.error(_ans["_error"])
elif _ans:
    if _ans.get("cannot_answer_from_packet"):
        st.warning(f"**Not answerable from what the estimate recorded.** "
                   f"{_ans['cannot_answer_from_packet']}")
    if _ans.get("answer"):
        st.markdown(_ans["answer"])

    if _ans.get("gaps"):
        st.markdown("**The gaps this answer refers to**")
        for g in _ans["gaps"]:
            st.info(f"**{g['gap']}** - {g['detail']}\n\n"
                    f"Costs: {g['costs']}.\n\n"
                    f"To close it: {g['closes_it']}.")

    with st.expander(f"Every measured gap ({len(_ans.get('all_gaps') or [])})"):
        for g in _ans.get("all_gaps") or []:
            st.markdown(f"- **{g['gap']}**: {g['detail']}  \n"
                        f"  *costs* {g['costs']}  \n"
                        f"  *to close it* {g['closes_it']}")
        if not _ans.get("all_gaps"):
            st.caption("No gaps measured - unusual, and worth checking against "
                       "the coverage figures above rather than believed.")
    st.caption(_ans.get("note", ""))
