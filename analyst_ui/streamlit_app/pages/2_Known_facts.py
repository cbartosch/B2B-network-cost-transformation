import datetime as dt
import streamlit as st
import api_client as api

st.title("2. User-known facts register")
st.caption("Specification 0.1B - what the team already knows, captured as an "
           "attributable assumption. It never satisfies an evidence gate.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

with st.form("kf"):
    st.markdown("**Register a known fact**")
    a, b = st.columns(2)
    fact_class = a.selectbox("Fact class", [
        "Location footprint", "Current architecture hypothesis", "Public cost evidence",
        "Current vendor and product signals", "Contract and sourcing events",
        "Operating-model cost", "Transformation announcements", "Resilience assumptions",
        "Remote-user population", "Market serviceability"])
    subject = b.text_input("Subject", help="Entity, country, provider or contract concerned")

    c, d, e, f = st.columns(4)
    base = c.number_input("Value (base)", value=0.0)
    low = d.number_input("Low (optional)", value=0.0)
    high = e.number_input("High (optional)", value=0.0)
    unit = f.text_input("Unit", "sites")

    g, h, i = st.columns(3)
    asserted_by = g.text_input("Asserted by *", help="A named individual. Not a team or a role.")
    basis = h.selectbox("Basis", ["CLIENT_CONVERSATION", "INDUSTRY_KNOWLEDGE",
                                  "THIRD_PARTY_REPORT", "PRIOR_ENGAGEMENT", "UNSTATED"])
    verif = i.selectbox("Verifiability", ["PUBLICLY_VERIFIABLE", "CLIENT_CONFIRMABLE",
                                          "UNVERIFIABLE"])
    j, k = st.columns(2)
    adate = j.date_input("Assertion date", dt.date.today())
    conf = k.slider("Self-reported confidence", 0.0, 1.0, 0.6)

    if basis == "PRIOR_ENGAGEMENT":
        st.warning("A PRIOR_ENGAGEMENT fact may carry another client's confidential "
                   "information. It starts un-cleared and cannot influence the estimate "
                   "until a rights check passes (2.4).")

    if st.form_submit_button("Register"):
        if not asserted_by.strip():
            st.error("An unattributed known fact is rejected. Name the asserter.")
        else:
            r = api.post(f"/v1/outside-in/cases/{case_id}/known-facts", {
                "fact_class": fact_class, "subject": subject,
                "value_base": base or None, "value_low": low or None,
                "value_high": high or None, "unit": unit,
                "asserted_by": asserted_by, "assertion_date": str(adate),
                "basis": basis, "verifiability": verif,
                "self_reported_confidence": conf})
            if "_error" in r:
                st.error(r["_error"])
            else:
                if r.get("range_widened_from_point"):
                    st.info("Point value widened to a range; the widening is shown in the record.")
                st.success(f"Registered as {r['evidence_origin']}")
                st.rerun()

st.divider()
facts = api.get(f"/v1/outside-in/cases/{case_id}/known-facts").get("known_facts", [])
if not facts:
    st.info("No known facts registered. This is fine - the V0 will run without them.")
else:
    for f in facts:
        state = f["corroboration_state"]
        icon = {"CORROBORATED": "[+]", "CONTRADICTED": "[!]",
                "UNCORROBORATED": "[-]"}.get(state, "[ ]")
        with st.expander(f"{icon} {f['fact_class']} - {f['subject']} "
                         f"({f['value_base']} {f['unit'] or ''}) - {state}"):
            st.write({"asserted_by": f["asserted_by"], "assertion_date": f["assertion_date"],
                      "basis": f["basis"], "verifiability": f["verifiability"],
                      "rights_cleared": f["rights_cleared"],
                      "self_reported_confidence": f["self_reported_confidence"]})
            if f.get("corroboration_note"):
                st.caption(f["corroboration_note"])
            if f.get("provenance"):
                chain = api.get(f["provenance"])
                if "_error" not in chain:
                    rec = chain.get("provider_record") or {}
                    st.markdown("**Corroborating evidence**")
                    st.write({
                        "agent run": chain.get("corroborated_by_agent_run"),
                        "provider": rec.get("provider"),
                        "provider_request_id": rec.get("provider_request_id"),
                        "provider_response_id": rec.get("provider_response_id"),
                        "at": rec.get("provider_request_at"),
                        "provenance_strength": rec.get("provenance_strength")})
                    st.caption(chain.get("note") or "")
                    if not chain.get("verifiable_with_provider"):
                        st.warning("This corroboration carries no provider request "
                                   "identifier, so it cannot be spot-checked.")
            cols = st.columns(2)
            if not f["rights_cleared"]:
                who = cols[0].text_input("Rights cleared by", key=f"rc_{f['known_fact_id']}")
                if cols[0].button("Clear rights", key=f"rb_{f['known_fact_id']}", disabled=not who):
                    api.post(f"/v1/outside-in/known-facts/{f['known_fact_id']}:clear-rights",
                             {"cleared_by": who})
                    st.rerun()
            if f["verifiability"] == "PUBLICLY_VERIFIABLE" and state == "PENDING":
                if cols[1].button("Corroborate (LIVE)", key=f"co_{f['known_fact_id']}"):
                    with st.spinner("Calling provider..."):
                        r = api.post(
                            f"/v1/outside-in/known-facts/{f['known_fact_id']}:corroborate",
                            {"provider": "anthropic", "mode": "LIVE"})
                    if "_error" in r:
                        st.error(f"Run failed closed: {r['_error']}")
                    else:
                        st.success(f"{r['corroboration_state']}")
                        st.rerun()
    st.caption("A corroborated fact is superseded by the public fact that corroborated it "
               "and stops counting toward asserted share (0.6A).")
