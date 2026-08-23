import streamlit as st
import api_client as api

st.title("3. Pre-flight readiness check")
st.caption("Specification 0.1C - every knowable constraint moved in front of the run.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

mode = st.radio("Intended execution mode", ["LIVE", "DETERMINISTIC_ONLY"], horizontal=True)

if st.button("Run readiness check", type="primary"):
    # POST, not GET - reading the report must not create one, which used to
    # silently invalidate a prior acknowledgement.
    st.session_state["preflight"] = api.post(
        f"/v1/outside-in/cases/{case_id}/preflight:run", {"mode": mode})

report = st.session_state.get("preflight")
if not report:
    st.info("Run the check to see what this V0 will and will not be able to establish.")
    st.stop()
if "_error" in report:
    st.error(report["_error"]); st.stop()

if report["blocked"]:
    st.error(f"**BLOCKED** - {len(report['blocks'])} condition(s) open. "
             f"The V0 run cannot begin.")
else:
    st.success("No BLOCK conditions. Acknowledge the report to proceed.")

for c in report["conditions"]:
    if c["state"] == "BLOCK":
        st.error(f"**BLOCK - {c['item']}**  \n{c['detail']}")
    elif c["state"] == "WARN":
        st.warning(f"**WARN - {c['item']}**  \n{c['detail']}")
    else:
        st.success(f"**PASS - {c['item']}**  \n{c['detail']}")

st.divider()
if not report["blocked"]:
    who = st.text_input("Acknowledged by (your name)")
    if st.button("Acknowledge and unlock V0", disabled=not who):
        r = api.post(f"/v1/outside-in/cases/{case_id}/preflight:acknowledge",
                     {"report_id": report["report_id"], "acknowledged_by": who})
        if "_error" in r:
            st.error(r["_error"])
        else:
            st.success("Acknowledged. The report is persisted and will be reproduced "
                       "beside the published estimate.")
