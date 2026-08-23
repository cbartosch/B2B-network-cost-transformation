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
                        [r["agent_run_id"] for r in runs])
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
