import pandas as pd
import streamlit as st
import api_client as api

st.title("7. Execution integrity")
st.caption("Specification 7.2C - provenance is proven by the provider record, not "
           "asserted by the application.")

health = api.get("/v1/health", deep=True)
if "_error" in health:
    st.error(f"API unreachable: {health['_error']}")
    st.stop()
a, b = st.columns(2)
a.metric("Environment", health.get("environment", "?"))
b.metric("Providers configured",
         ", ".join([k for k, v in health.get("providers", {}).items() if v]) or "NONE")

st.divider()
st.subheader("Can this container reach the internet?")
st.caption("\"Providers configured\" above means a key is set - it passes on a "
           "container that can reach nothing. This fetches data that changes, so "
           "the answer can be read rather than trusted.")

if st.button("Check egress now"):
    st.session_state["_reach"] = api.get(
        "/v1/integrity/reachability",
        **({"case_id": st.session_state["case_id"]}
           if st.session_state.get("case_id") else {}))

reach = st.session_state.get("_reach")
if reach and "_error" in reach:
    st.error(f"Could not run the check: {reach['_error']}")
elif reach:
    if reach.get("reachable"):
        st.success("Reachable. The readings below are live.")
    else:
        st.error("Not reachable. A research run cannot verify any source from "
                 "here, so no domain can reach EVIDENCED_PUBLIC - which surfaces "
                 "as empty findings rather than as a network fault.")

    cols = st.columns(3)
    by_step = {s["step"]: s for s in reach.get("steps", [])}
    clock = by_step.get("independent clock", {})
    weather = by_step.get("weather at headquarters", {})
    cols[0].metric("Remote clock",
                   (clock.get("remote_time") or "-")[11:19] if clock.get("ok") else "-",
                   clock.get("skew_note") if clock.get("ok") else "unavailable")
    cols[1].metric(f"Weather - {reach.get('asked_about', '?')}",
                   f"{weather.get('temperature')}" if weather.get("ok") else "-",
                   weather.get("local_time") if weather.get("ok") else "unavailable")
    cols[2].metric("Egress proxy",
                   reach.get("transport", {}).get("egress_proxy") or "none")

    st.caption(f"Location basis: {reach.get('location_basis')}. "
               f"Verification: {reach.get('transport', {}).get('verification')}.")
    for step in reach.get("steps", []):
        (st.success if step["ok"] else st.error)(
            f"**{step['step']}** - {step['detail']}")
    with st.expander("Full response"):
        st.json(reach)

st.divider()
st.subheader("Agent runs")
# An API failure must not render as an empty table: "no runs recorded" and
# "could not ask" are different answers, and on an integrity page the
# difference is the whole point.
_runs = api.get("/v1/agent-runs")
if "_error" in _runs:
    st.error(f"Could not read agent runs: {_runs['_error']}")
    st.stop()
runs = _runs.get("runs", [])
if not runs:
    st.info("No agent runs yet.")
else:
    df = pd.DataFrame(runs)[["agent_run_id", "agent_id", "execution_mode", "environment",
                             "status", "produced_without_llm", "error"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    pick = st.selectbox("Inspect provenance for run",
                        [r["agent_run_id"] for r in runs], key="ei_run_pick")
    _prov = api.get(f"/v1/agent-runs/{pick}/provenance")
    if "_error" in _prov:
        st.error(f"Could not read provenance: {_prov['_error']}")
        st.stop()
    prov = _prov.get("llm_runs", [])
    if prov:
        st.success("Liveness proof present.")
        st.dataframe(pd.DataFrame(prov)[
            ["provider", "model", "provider_response_id", "provider_request_at",
             "input_tokens", "output_tokens", "latency_ms"]],
            use_container_width=True, hide_index=True)
        st.caption("`provider_response_id` carries a database uniqueness constraint. "
                   "Presenting a stored response as a fresh LIVE call is rejected by the "
                   "storage layer, not by a check that could be bypassed.")
    else:
        st.warning("No provider record for this run. A LIVE run in this state cannot "
                   "reach SUCCEEDED.")

st.divider()
st.subheader("Rejected runs")
_rej = api.get("/v1/agent-runs/rejections")
rej = [] if "_error" in _rej else _rej.get("rejections", [])
if "_error" in _rej:
    st.warning(f"Could not read rejections: {_rej['_error']}")
st.dataframe(pd.DataFrame(rej), use_container_width=True, hide_index=True) if rej else \
    st.caption("None. In a PRODUCTION environment a MOCK request would be rejected here "
               "at run creation, before it could execute or reach the interface.")

st.divider()
st.subheader("Provider usage reconciliation (7.2E)")
rec = api.get("/v1/integrity/reconciliation")
if "_error" in rec:
    st.warning(f"Could not read reconciliation state: {rec['_error']}")
    rec = {}
st.write(f"Status: **{rec.get('status')}**")
st.caption(rec.get("note", ""))
if rec.get("claimed"):
    st.dataframe(pd.DataFrame(rec["claimed"]), use_container_width=True, hide_index=True)

# ------------------------------------------------- incidents and quarantine
st.divider()
st.subheader("Integrity incidents and quarantined rows")
st.caption(
    "An incident is a control that fired. A quarantined row is data a control "
    "would not let through and did not delete - most often a research finding "
    "about the wrong entity, which is informative twice over: the perimeter "
    "may be wrong, or an alias may be missing.")

_inc = api.get("/v1/integrity/incidents?include_resolved=false")
if "_error" in _inc:
    st.error(_inc["_error"])
else:
    _rows = _inc.get("incidents") or []
    _q = _inc.get("quarantined_rows", 0)
    (st.success if not _rows else st.warning)(
        f"{_inc.get('open', len(_rows))} open incident(s), "
        f"{_q} quarantined row(s) retained.")
    if _rows:
        st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                     hide_index=True)
    st.caption(_inc.get("note", ""))
    if st.checkbox("Include resolved incidents", key="ei_resolved"):
        _all = api.get("/v1/integrity/incidents?include_resolved=true")
        if "_error" not in _all and (_all.get("incidents") or []):
            st.dataframe(pd.DataFrame(_all["incidents"]),
                         use_container_width=True, hide_index=True)

# ---------------------------------------------------------- attestation
st.divider()
st.subheader("Provider call attestation")
st.caption(
    "Every provider call in the window, with the response identifier the "
    "provider issued. This is the artefact an operator compares against the "
    "provider's own console - if a call is not in both, one of the two records "
    "is wrong, and that is worth knowing before a number built on it is "
    "published.")

_days = st.number_input("Window (days)", 1, 365, 30, key="ei_days")
if st.button("Build attestation"):
    st.session_state["_att"] = api.get(f"/v1/integrity/attestation?days={int(_days)}")

_att = st.session_state.get("_att")
if _att and "_error" in _att:
    st.error(_att["_error"])
elif _att:
    _calls = _att.get("calls") or _att.get("runs") or []
    st.info(f"{len(_calls)} call(s) in the last {int(_days)} day(s).")
    if _calls:
        st.dataframe(pd.DataFrame(_calls), use_container_width=True,
                     hide_index=True)
        import json as _json
        st.download_button(
            "Download as JSON",
            data=_json.dumps(_att, indent=2, default=str),
            file_name=f"attestation_{int(_days)}d.json",
            mime="application/json",
            help="For comparison against the provider console, and for an "
                 "auditor who should not have to take this screen's word.")
    for _k, _v in _att.items():
        if _k not in ("calls", "runs") and not isinstance(_v, (list, dict)):
            st.caption(f"{_k}: {_v}")

# ------------------------------------------------------------- TLS pins
st.divider()
st.subheader("TLS pins")
st.caption(
    "The keys observed on each provider host, and when the current pin set "
    "expires. A pin that lapses fails every provider call at once, which is a "
    "deadline worth seeing before it passes rather than after.")

_pins = api.get("/v1/integrity/tls-pins?days=30")
if "_error" in _pins:
    st.error(_pins["_error"])
else:
    _observed = _pins.get("pins") or _pins.get("hosts") or []
    if isinstance(_observed, dict):
        _observed = [{"host": k, **(v if isinstance(v, dict) else {"value": v})}
                     for k, v in _observed.items()]
    if _observed:
        st.dataframe(pd.DataFrame(_observed), use_container_width=True,
                     hide_index=True)
    for _k, _v in _pins.items():
        if _k not in ("pins", "hosts") and not isinstance(_v, (list, dict)):
            st.caption(f"{_k}: {_v}")
    if not _observed:
        st.info("No pin observations recorded yet. Pins are observed on the "
                "first outbound provider call.")
