import pandas as pd
import streamlit as st
import api_client as api

st.title("8. Savings recommendation")
st.caption("Specification 10/11 (as far as this was built against) - LLM-07 proposes a "
           "scenario and percentile from an already-computed estimate; the dollar figure "
           "is looked up, never taken from the model's own text. LLM-06 narrates the "
           "decided recommendation.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()


api.show_flash()
snaps = api.get(f"/v1/outside-in/cases/{case_id}/estimates").get("snapshots", [])
if not snaps:
    st.warning("Run a V0 estimate first (page 6) - a recommendation is made against an "
               "already-computed snapshot, never against fresh arithmetic of its own.")
    st.stop()

snap_label = {f"{s['estimate_snapshot_id'][:8]} - {s['version_label']} "
             f"({s['created_at'][:19]})": s["estimate_snapshot_id"] for s in snaps}
picked = st.selectbox("Estimate snapshot", list(snap_label), key="sr_picked")
snapshot_id = snap_label[picked]

st.subheader("Generate a recommendation")
c1, c2 = st.columns(2)
mode = c1.selectbox("Mode", ["LIVE", "DETERMINISTIC_ONLY"],
                    help="DETERMINISTIC_ONLY never calls a model - a fixed rule (highest "
                         "base-case savings, base percentile) instead. Neither mode is "
                         "ever chosen automatically for you; a failed LIVE call fails, it "
                         "does not fall back to this silently.", key="sr_mode")
provider = c2.selectbox("Provider", ["anthropic", "openai"], disabled=(mode != "LIVE"), key="sr_provider")
if st.button("Run LLM-07", type="primary"):
    with st.spinner("Running LLM-07..."):
        r = api.post(f"/v1/outside-in/cases/{case_id}/estimates/{snapshot_id}"
                     f"/recommendation:run", {"mode": mode, "provider": provider})
    if "_error" in r:
        st.error(r["_error"])
    else:
        api.flash(f"{r['label']}: scenario {r['scenario_code']}, {r['percentile']} "
                   f"percentile, {r['gross_run_rate_savings'][r['percentile']]}/yr.")
        st.rerun()

st.subheader("Recommendations for this case")
recs = api.get(f"/v1/outside-in/cases/{case_id}/recommendations").get("recommendations", [])
if not recs:
    st.caption("None yet.")

for rec in recs:
    savings = rec["gross_run_rate_savings"][rec["percentile"]]
    header = (f"{rec['scenario_code']} / {rec['percentile']} - {savings}/yr "
             f"- {rec['label']}")
    with st.expander(header):
        st.write(f"**Basis:** {rec['basis']}")
        # A gross run-rate saving was the whole story until 4.165: no one-time
        # cost, no dual running, no payback. A reader comparing scenarios was
        # comparing prizes without their price.
        _t = rec.get("transition")
        if _t:
            st.markdown("**What it costs to get there**")
            _c1, _c2, _c3 = st.columns(3)
            _c1.metric("One-time", _t["one_time_cost"]["base"])
            _c2.metric("Dual running", _t["dual_running_cost"]["base"])
            _c3.metric("First-year net", _t["first_year_net"])
            _pb = _t["payback_months"]
            st.caption(
                f"Payback {_pb['base']} month(s) at base, "
                f"{_pb['optimistic']} optimistic, {_pb['pessimistic']} "
                f"pessimistic - against a programme of "
                f"{_t['programme_months']} month(s). "
                + _t["note"])
            st.warning(_t["payback_basis"])
            with st.expander(f"{len(_t['not_modelled'])} cost categories this "
                             f"model has no basis for"):
                for _n in _t["not_modelled"]:
                    st.caption(f"   {_n}")
        else:
            st.caption(
                "No transition cost is modelled for this recommendation, so "
                "the saving above is gross and there is no payback. Re-run V0 "
                "with a site count for the net view.")
        if rec["material_levers"]:
            st.warning(f"Material lever(s) (\u2265 governed share of current TCO): "
                      f"{', '.join(rec['material_levers'])}")
            if rec["approved_by"]:
                st.success(f"Approved by {rec['approved_by']} at {rec['approved_at']}")
            else:
                name = st.text_input("Approve as (named individual, not a role or team)",
                                     key=f"appr_{rec['recommendation_id']}")
                if st.button("Approve", key=f"appr_btn_{rec['recommendation_id']}"):
                    a = api.post(
                        f"/v1/outside-in/cases/{case_id}/recommendations/"
                        f"{rec['recommendation_id']}:approve", {"approved_by": name})
                    if "_error" in a:
                        st.error(a["_error"])
                    else:
                        st.rerun()
        else:
            st.caption("No lever here is at or above the material-share threshold.")

        st.markdown("---")
        if rec["narrative"]:
            st.write(f"**Narrative ({rec['narrative_label']}):** {rec['narrative']}")
        nc1, nc2, nc3 = st.columns(3)
        n_mode = nc1.selectbox("Mode", ["LIVE", "DETERMINISTIC_ONLY"],
                               key=f"nmode_{rec['recommendation_id']}")
        n_provider = nc2.selectbox("Provider", ["anthropic", "openai"],
                                   disabled=(n_mode != "LIVE"),
                                   key=f"nprov_{rec['recommendation_id']}")
        n_final = nc3.checkbox("Final (refused if material and unapproved)",
                               key=f"nfinal_{rec['recommendation_id']}")
        if st.button("Run LLM-06", key=f"narr_btn_{rec['recommendation_id']}"):
            with st.spinner("Running LLM-06..."):
                n = api.post(
                    f"/v1/outside-in/cases/{case_id}/recommendations/"
                    f"{rec['recommendation_id']}/narrative:run",
                    {"mode": n_mode, "provider": n_provider, "final": n_final})
            if "_error" in n:
                st.error(n["_error"])
            else:
                st.rerun()


# ------------------------------------------------------ validation capture
st.divider()
st.subheader("Why the estimate moved")
st.caption(
    "Specification 0.5D. The lineage said an estimate superseded another; the "
    "bridge says why, in eight driver categories that must add up exactly. A "
    "residual is reported rather than folded into the nearest driver - folding "
    "it makes the arithmetic tidy and the explanation false.")

_br = api.get(f"/v1/outside-in/cases/{case_id}/delta-bridge")
if "_error" in _br:
    st.error(f"Could not read the bridges: {_br['_error']}")
else:
    for _b in _br.get("bridges") or []:
        _head = (f"{_b['from_snapshot_id'][:8]} -> {_b['to_snapshot_id'][:8]}  "
                 f"{_b['total_change']}")
        with st.expander(_head + ("" if _b["reconciles"]
                                  else f"  (residual {_b['residual']})")):
            _pol = _b.get("policy") or {}
            if _pol.get("moved"):
                st.warning(
                    "Model settings moved between these snapshots: "
                    + ", ".join(sorted(_pol["moved"]))
                    + ". That is about the model rather than the client, and "
                      "it is shown before the drivers for that reason.")
            st.dataframe(pd.DataFrame([
                {"driver": d["driver"], "value": d["value"],
                 "earliest stage": d["earliest_stage"],
                 "because": "; ".join(d.get("because") or [])}
                for d in _b["drivers"] if d["value"] not in ("0", "0.00")]),
                use_container_width=True, hide_index=True)
            if _b["reconciles"]:
                st.success("The drivers account for the whole movement.")
            else:
                st.error(
                    f"{_b['residual']} of the {_b['total_change']} change is "
                    f"unattributed. The bridge does not reconcile, and the "
                    f"missing part is the one somebody will ask about.")
    if not (_br.get("bridges") or []):
        st.caption(
            "No bridge built on this case. One is built between two estimate "
            "snapshots, so there is nothing to explain until a second estimate "
            "exists.")

st.divider()
st.subheader("Validation case")
st.caption(
    "What this estimate said, held against what turns out to be true. The "
    "estimated half is read from the snapshot and never typed - a case opened "
    "after the outturn is known would let the estimate be adjusted to match, "
    "and a corpus that can be fitted measures nothing.")

_vc = api.get("/v1/outside-in/validation-cases")
if "_error" in _vc:
    st.error(f"Could not read the validation cases: {_vc['_error']}")
else:
    _mine = [c for c in (_vc.get("cases") or []) if c["case_id"] == case_id]
    _stats = _vc.get("statistics") or {}
    st.caption(
        f"{_stats.get('cases_included', 0)} case(s) of an empirical tier across "
        f"all engagements; {len(_vc.get('awaiting_actuals') or [])} awaiting an "
        f"outturn. "
        + (_stats.get("note") or ""))

    _snaps = api.get(f"/v1/outside-in/cases/{case_id}/estimates")
    _ids = [e["estimate_snapshot_id"] for e in (_snaps or [])
            if isinstance(_snaps, list)] if isinstance(_snaps, list) else []
    _open_on = [i for i in _ids
                if i not in {c["estimate_snapshot_id"] for c in _mine
                             if c.get("estimate_snapshot_id")}]
    if _open_on:
        _pick = st.selectbox("Open a case against", _open_on,
                             key=f"vc_snap_{case_id[:8]}")
        _by = st.text_input("Opening as (your name)", key=f"vc_by_{case_id[:8]}")
        if st.button("Open validation case", disabled=not _by.strip()):
            _r = api.post(
                f"/v1/outside-in/cases/{case_id}/estimates/"
                f"{_pick}:validation-case",
                {"opened_by": _by})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash(_r.get("note", "Case opened."))
                st.rerun()

    for _c in _mine:
        with st.expander(
                f"{_c['validation_case_id'][:8]} - "
                + ("comparable" if _c["comparable"] else "awaiting the outturn")):
            st.write("**What the model said**")
            st.json(_c["estimated"])
            if _c["comparable"]:
                st.write("**What turned out to be true**")
                st.json(_c["actual"])
                st.caption(f"Tier {_c['evidence_tier']}, recorded by "
                           f"{_c['recorded_by']}.")
            else:
                st.caption(
                    "Record the outturn when the engagement finishes - often a "
                    "year later, often not the same analyst. Until then this "
                    "case is held and counts toward nothing.")
