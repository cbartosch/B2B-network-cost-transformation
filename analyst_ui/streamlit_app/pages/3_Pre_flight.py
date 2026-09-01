import streamlit as st
import api_client as api

st.title("3. Pre-flight readiness check")
st.caption("Specification 0.1C - every knowable constraint moved in front of the run.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()


api.show_flash()
# Which page clears which condition. A gate that lists what is wrong without
# saying where to fix it makes the analyst hunt; the mapping is cheap and the
# hunting is not.
# Keys must match preflight condition names EXACTLY or the guidance never
# renders. Two of these were invented from memory on the first pass and matched
# nothing; the list below was taken from a real report and is checked by
# test_preflight_guidance_covers_every_condition.
WHERE_TO_FIX = {
    "Entity resolution": "Page 1 — resolve and confirm the subject entity.",
    "Mandatory intake": "Page 1 — complete the intake fields named above.",
    "Provider availability": "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env and "
                             "restart. Deterministic paths still run without one.",
    "Prior coverage": "Page 5 — dispose more domains, or accept a PARTIAL V0.",
    "Prior-engagement rights": "Page 2 — clear the rights flag on the facts named.",
    "Known-fact contradictions": "Page 2 — resolve the contradictions named.",
    "Financial policy": "Page 1 — set the currency, price year and discount rate set.",
    "Benchmark release availability": "Expected before any engagement reaches V2; V0 "
                                      "runs on reference priors.",
}

# Read the existing report rather than creating one. This page used to know a
# report only if you pressed the button in this session: returning to it showed
# nothing, and pressing the button again silently superseded a prior
# acknowledgement. The GET endpoint has always existed and was never used.
stored = api.get(f"/v1/outside-in/cases/{case_id}/preflight")
report = None if "_error" in stored else stored

# Session state outlives a case switch, so a cached report can belong to a
# different case. The report now carries case_id precisely so this is checkable.
cached = st.session_state.get("preflight")
if cached and cached.get("case_id") == case_id:
    report = cached
elif cached:
    st.session_state.pop("preflight", None)

mode = st.radio("Intended execution mode", ["LIVE", "DETERMINISTIC_ONLY"],
                horizontal=True,
                help="LIVE requires a configured provider. DETERMINISTIC_ONLY "
                     "never calls a model.")

col_run, col_note = st.columns([1, 3])
if col_run.button("Run readiness check", type="primary"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/preflight:run", {"mode": mode})
    if "_error" not in r:
        st.session_state["preflight"] = r
        report = r
    else:
        st.error(r["_error"])
if report and report.get("acknowledged_by"):
    col_note.caption("Running the check again creates a **new** report and supersedes "
                     "the acknowledgement below.")

if not report:
    st.info("No readiness check has been run for this case yet. Run one to see what "
            "this V0 will and will not be able to establish.")
    st.stop()

if report["blocked"]:
    st.error(f"**BLOCKED** - {len(report['blocks'])} condition(s) open. "
             f"The V0 run cannot begin.")
elif report.get("acknowledged_by"):
    st.success(f"Cleared and acknowledged by **{report['acknowledged_by']}**. "
               f"V0 is unlocked for this case.")
else:
    st.success("No BLOCK conditions. Acknowledge the report to unlock V0.")

for c in report["conditions"]:
    fix = WHERE_TO_FIX.get(c["item"])
    if c["state"] == "BLOCK":
        st.error(f"**BLOCK — {c['item']}**  \n{c['detail']}"
                 + (f"  \n*{fix}*" if fix else ""))
    elif c["state"] == "WARN":
        st.warning(f"**WARN — {c['item']}**  \n{c['detail']}")
    else:
        st.success(f"**PASS — {c['item']}**  \n{c['detail']}")

st.divider()
if report["blocked"]:
    st.caption("Clear the BLOCK conditions above, then run the check again. There is "
               "no override - a gate that can be waived silently is not a gate.")
elif report.get("acknowledged_by"):
    st.caption("Already acknowledged. Nothing further is needed here; continue to "
               "page 5 (Simulation) or page 6 (Run V0).")
else:
    who = st.text_input("Acknowledged by (your name)",
                        help="A named person, not a role or a team. Reproduced beside "
                             "the published estimate.")
    if st.button("Acknowledge and unlock V0", disabled=not who.strip(), type="primary"):
        r = api.post(f"/v1/outside-in/cases/{case_id}/preflight:acknowledge",
                     {"report_id": report["report_id"], "acknowledged_by": who.strip()})
        if "_error" in r:
            st.error(r["_error"])
        else:
            st.session_state.pop("preflight", None)
            api.flash("Acknowledged. The report is persisted and will be "
                      "reproduced beside the published estimate.")
            st.rerun()
