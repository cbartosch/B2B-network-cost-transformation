import pandas as pd
import streamlit as st
import api_client as api

st.title("9. V1 questionnaire and stage")
st.caption("Client-supplied answers map onto the 24-domain disposition contract as "
           "CLIENT_CONFIRMED - first-party data, stronger than an analyst assertion, "
           "weaker than an independently-checkable public source, and never a silent "
           "replacement for one.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

stage_info = api.get(f"/v1/outside-in/cases/{case_id}/stage")
if "_error" not in stage_info:
    c1, c2 = st.columns(2)
    c1.metric("Current stage", stage_info.get("current_stage", "V0"))
    c2.caption(f"Advanced by {stage_info.get('advanced_by') or '-'}")

q = api.get(f"/v1/outside-in/cases/{case_id}/questionnaire")
items = q.get("items", []) if "_error" not in q else []

if not items:
    if st.button("Create V1 questionnaire", type="primary"):
        api.post(f"/v1/outside-in/cases/{case_id}/questionnaire"); st.rerun()
    st.stop()

st.caption(f"{q['answered']} of {q['total']} answered.")

pc1, pc2 = st.columns(2)
pmode = pc1.selectbox("Prefill mode", ["LIVE", "DETERMINISTIC_ONLY"],
                      help="A prefill is a suggestion for the client to correct. It is "
                           "never counted as an answer.")
if pc2.button("Run LLM-02 prefill"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/questionnaire:prefill",
                 {"mode": pmode})
    st.error(r["_error"]) if "_error" in r else st.rerun()

st.dataframe(pd.DataFrame([
    {"Domain": i["domain_no"], "Question": i["question_text"],
     "Prefill": i["prefill_value"] or "-", "Prefill origin": i["prefill_label"] or "-",
     "Answer": i["answer_value"] or "-", "Answered by": i["answered_by"] or "-",
     "Mapping": i.get("mapping_state") or "-",
     "Adjudication": i.get("mapping_resolution") or "-"} for i in items]),
    use_container_width=True, hide_index=True)

st.subheader("Record an answer")
a1, a2, a3 = st.columns(3)
key = a1.selectbox("Question", [i["question_key"] for i in items])
val = a2.text_input("Client's answer")
who = a3.text_input("Answered by (named person at the client)")
if st.button("Save answer"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/questionnaire:answer",
                 {"question_key": key, "answer_value": val, "answered_by": who})
    st.error(r["_error"]) if "_error" in r else st.rerun()

st.subheader("Map answers onto the disposition contract")
st.caption("Upgrades a domain holding a benchmark prior, an analyst assertion or "
           "DECLARED_UNKNOWN. An answer meeting public evidence is flagged for a named "
           "person to adjudicate - it never overwrites it silently.")
mb = st.text_input("Mapped by (named person)", key="mapped_by")
if st.button("Run mapping"):
    r = api.post(f"/v1/outside-in/cases/{case_id}/questionnaire:map", {"mapped_by": mb})
    if "_error" in r:
        st.error(r["_error"])
    else:
        st.success(f"{r['upgraded']} upgraded, {r['requiring_adjudication']} need "
                   f"adjudication."); st.rerun()

conf = api.get(f"/v1/outside-in/cases/{case_id}/questionnaire/conflicts")
for c in (conf.get("conflicts", []) if "_error" not in conf else []):
    with st.expander(f"Adjudicate: {c['question_key']} (domain {c['domain_no']})"):
        st.write(c["mapping_note"])
        st.write(f"**Client said:** {c['answer_value']} — {c['answered_by']}")
        res = st.selectbox("Resolution", ["CLIENT_AGREES_WITH_PUBLIC",
                                          "CLIENT_CONTRADICTS_PUBLIC",
                                          "CLIENT_SUPERSEDES_PUBLIC"],
                           key=f"res_{c['item_id']}")
        note = st.text_input("Reason (required to supersede public evidence)",
                             key=f"note_{c['item_id']}")
        rby = st.text_input("Resolved by", key=f"rby_{c['item_id']}")
        if st.button("Record adjudication", key=f"btn_{c['item_id']}"):
            r = api.post(f"/v1/outside-in/cases/{case_id}/questionnaire:resolve-mapping",
                         {"question_key": c["question_key"], "resolution": res,
                          "resolved_by": rby, "note": note})
            st.error(r["_error"]) if "_error" in r else st.rerun()

st.subheader("Stage readiness")
if st.button("Assess readiness for V1"):
    api.post(f"/v1/outside-in/cases/{case_id}/stage:assess", {"target_stage": "V1"})
    st.rerun()

rep = (stage_info or {}).get("latest_report")
if rep:
    st.dataframe(pd.DataFrame(rep["conditions"]), use_container_width=True,
                 hide_index=True)
    if rep["blocked"]:
        st.warning("Blocked - resolve the BLOCK conditions above.")
    else:
        s1, s2 = st.columns(2)
        ack = s1.text_input("Acknowledge as", key="ack_by")
        if s1.button("Acknowledge"):
            api.post(f"/v1/outside-in/cases/{case_id}/stage:acknowledge",
                     {"report_id": rep["report_id"], "acknowledged_by": ack})
            st.rerun()
        adv = s2.text_input("Advance as", key="adv_by")
        if s2.button("Advance to V1", type="primary"):
            r = api.post(f"/v1/outside-in/cases/{case_id}/stage:advance",
                         {"target_stage": "V1", "advanced_by": adv})
            st.error(r["_error"]) if "_error" in r else st.rerun()
