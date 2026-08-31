import datetime as dt

import pandas as pd
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
    subject = b.text_input("Subject *",
                           help="The entity, country, provider or contract the "
                                "claim is about. Corroboration searches for "
                                "public sources about this subject, so without "
                                "one there is nothing to look for.")

    c, d, e, f = st.columns(4)
    # value=None, not 0.0. The field defaulted to 0.0 and the payload then did
    # `base or None`, so an untouched field silently became "no value" - and a
    # legitimate zero became one too. The fact registered as "(None sites)"
    # with an empty subject, and every stage downstream then behaved correctly
    # on something that should never have been storable.
    base = c.number_input("Value (base) *", value=None, placeholder="e.g. 340")
    low = d.number_input("Low (optional)", value=None)
    high = e.number_input("High (optional)", value=None)
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
        problems = []
        if not asserted_by.strip():
            problems.append("An unattributed known fact is rejected. Name the asserter.")
        if not subject.strip():
            problems.append("Name the subject. Corroboration looks for public "
                            "sources about a named subject.")
        if base is None and low is None and high is None:
            problems.append("Give a value - a point in base, or a range in low "
                            "and high. If the number is genuinely unknown, "
                            "leave the domain DECLARED_UNKNOWN rather than "
                            "asserting an empty fact.")
        if problems:
            for msg in problems:
                st.error(msg)
        else:
            r = api.post(f"/v1/outside-in/cases/{case_id}/known-facts", {
                "fact_class": fact_class, "subject": subject,
                # No `or None`: that coerced a legitimate zero to absent
                # as well as an untouched field.
                "value_base": base, "value_low": low, "value_high": high,
                "unit": unit,
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
        _malformed = not (f.get("subject") or "").strip() or f.get("value_base") is None
        _label = (f"{icon} {f['fact_class']} - "
                  f"{f['subject'] or 'NO SUBJECT'} "
                  f"({'NO VALUE' if f['value_base'] is None else f['value_base']} "
                  f"{f['unit'] or ''}) - "
                  f"{'MALFORMED - cannot be corroborated' if _malformed else state}")
        with st.expander(_label):
            if _malformed:
                st.error(
                    "This fact carries no subject or no value, so there is no "
                    "claim to check against public sources - corroboration "
                    "will keep returning UNCORROBORATED however many times it "
                    "is run. It predates the validation that now refuses such "
                    "a fact at registration. Remove it and register it again "
                    "with a subject and a value.")
                if st.button("Remove this malformed fact",
                             key=f"rm_{f['known_fact_id']}"):
                    rr = api.post(
                        f"/v1/outside-in/known-facts/{f['known_fact_id']}:void",
                        {"voided_by": "analyst"})
                    if "_error" in rr:
                        st.error(rr["_error"])
                    else:
                        st.rerun()
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
                        st.session_state[f"obs_{f['known_fact_id']}"] = r
                        st.success(f"{r['corroboration_state']}")
                        st.rerun()

            # Whatever the verdict, show what the sources said. A result that
            # reports only a state throws away the figures the search found,
            # which are usually the answer to the question actually being
            # asked - here, six sources giving branch counts against an
            # assertion made in sites.
            _res = st.session_state.get(f"obs_{f['known_fact_id']}")
            if isinstance(_res, dict):
                _obs = _res.get("observed") or {}
                _rows = (_obs.get("comparable") or []) + (_obs.get("other_unit") or [])
                if _rows:
                    st.markdown("**What public sources said**")
                    st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                                 hide_index=True)
                if _obs.get("other_unit") and not _obs.get("comparable"):
                    st.info("These are in a different unit from the assertion, "
                            "so they neither confirm nor contradict it. If the "
                            "asserted total is meant to be these plus other "
                            "site types, research domain 2 and promote the "
                            "per-type counts - a sum is a derivation and "
                            "belongs where its inputs are recorded, not in a "
                            "comparison that would then report a number no "
                            "source stated.")
                for _u in _res.get("unresolved_reasons") or []:
                    st.caption(f"- {_u}")
    st.caption("A corroborated fact is superseded by the public fact that corroborated it "
               "and stops counting toward asserted share (0.6A).")
