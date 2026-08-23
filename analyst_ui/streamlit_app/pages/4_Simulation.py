import time

import pandas as pd
import streamlit as st
import api_client as api

st.title("4. Topology and architecture simulation")
st.caption("Specification 0.3B - a sizing instrument, not evidence. Never written to "
           "the topology graph; diversity state is always SIMULATED.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

st.info("Simulated structure can never set EVIDENCED, never supports a resilience-dependent "
        "lever, and is permanently barred from benchmark promotion (5.6).")

st.subheader("Footprint")
default = pd.DataFrame([
    {"country": "GB", "archetype": "BRANCH", "sites": 120},
    {"country": "DE", "archetype": "BRANCH", "sites": 80},
    {"country": "US", "archetype": "LARGE_OFFICE", "sites": 12},
    {"country": "GB", "archetype": "DC", "sites": 2},
])
fp = st.data_editor(default, num_rows="dynamic", use_container_width=True)

c1, c2 = st.columns(2)
seed = c1.number_input("Seed", 0, 10**9, 42,
                       help="The whole ensemble is reproducible from this one integer")
size = c2.number_input("Ensemble size", 1, 200, 25)

if st.button("Run simulation", type="primary"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/simulations:run",
                 {"seed": int(seed), "ensemble_size": int(size),
                  "footprint": fp.to_dict("records")})
    if "_error" in r:
        st.error(r["_error"])
    else:
        st.session_state["sim_run_id"] = r["simulation_run_id"]
        st.session_state.pop("sim", None)
        st.rerun()

run_id = st.session_state.get("sim_run_id")
if run_id and "sim" not in st.session_state:
    state = api.get(f"/v1/outside-in/simulations/{run_id}", include_output=True)
    if "_error" in state:
        st.error(state["_error"])
    elif state["status"] in ("QUEUED", "RUNNING", "CANCELLING"):
        st.progress(min(1.0, (state["percent"] or 0) / 100),
                    text=f"{state['status']} - pass {state['completed']} of "
                         f"{state['total']} ({state['percent']}%)")
        c1, c2 = st.columns(2)
        if c1.button("Cancel"):
            api.post(f"/v1/outside-in/simulations/{run_id}:cancel")
            st.rerun()
        if c2.button("Refresh"):
            st.rerun()
        time.sleep(1.5)
        st.rerun()
    elif state["status"] == "CANCELLED":
        st.warning(f"Cancelled after {state['completed']} of {state['total']} passes. "
                   f"Completed passes are kept - resuming continues from there and "
                   f"produces the identical result.")
        if st.button("Resume"):
            r = api.post(f"/v1/outside-in/simulations/{run_id}:resume")
            if r.get("note"):
                st.info(r["note"])
            st.rerun()
    elif state["status"] == "FAILED":
        st.error(f"Failed: {state.get('error')}")
        if st.button("Resume from checkpoint"):
            r = api.post(f"/v1/outside-in/simulations/{run_id}:resume")
            if r.get("note"):
                st.info(r["note"])
            st.rerun()
    elif state["status"] == "SUCCEEDED":
        st.session_state["sim"] = {"simulation_run_id": run_id,
                                   "output_hash": state["output_hash"],
                                   "output": state["output"]}
        st.success(f"Run `{run_id[:8]}` - output hash `{state['output_hash'][:16]}...`")

sim = st.session_state.get("sim")
if sim:
    o = sim["output"]
    a, b, c, d = st.columns(4)
    a.metric("Sites", o["sites"])
    b.metric("Primary circuits", o["circuits_primary"]["base"],
             "deterministic from footprint", delta_color="off")
    c.metric("Backup circuits", o["circuits_backup"]["base"],
             f"{o['circuits_backup']['low']} - {o['circuits_backup']['high']} (simulated)",
             delta_color="off")
    d.metric("Dual-access sites", o["dual_access_sites"]["base"])
    st.caption("Only the backup count is decided by the seeded draw - the primary count "
               "follows from the footprint you supplied. That split is what the derived "
               "simulated share in step 6 is computed from.")
    st.caption(f"Model `{o['model_version']}` seed `{o['seed']}` ensemble {o['ensemble_size']}. "
               f"Re-running with the same seed and priors reproduces this hash exactly.")
    st.markdown("**Sample simulated edges** - note the diversity state.")
    st.dataframe(pd.DataFrame(o["sample_topology"]["edges"][:25]), use_container_width=True)

runs = api.get(f"/v1/outside-in/cases/{case_id}/simulations").get("runs", [])
if runs:
    st.divider(); st.subheader("Run history")
    st.caption("Simulation runs asynchronously. A cancelled run keeps its completed "
               "passes and resumes to the identical result, because every pass is a "
               "pure function of seed plus index.")
    st.dataframe(pd.DataFrame(runs), use_container_width=True)
