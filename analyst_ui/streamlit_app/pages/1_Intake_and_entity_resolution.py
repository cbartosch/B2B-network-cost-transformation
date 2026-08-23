import streamlit as st
import api_client as api

st.title("1. Intake and entity resolution")
st.caption("Specification 0.1A - no research, agent run, prior lookup or calculation "
           "may execute against a case until the subject entity is confirmed.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select or create a case on the home page first.")
    st.stop()

case = api.get(f"/v1/outside-in/cases/{case_id}")

st.subheader("Mandatory intake block")
with st.form("intake"):
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Subject entity legal name *", case.get("subject_entity_legal_name") or "",
                         help="Exact registered legal name - not a trading or brand name")
    ident = c2.text_input("Entity identifier *", case.get("entity_identifier") or "",
                          help="LEI, ticker plus exchange, registration number or primary domain")
    dom = c3.text_input("Country of domicile *", case.get("country_of_domicile") or "", max_chars=2)

    c4, c5, c6 = st.columns(3)
    perimeter = c4.selectbox("Group perimeter *",
                             ["SINGLE_ENTITY", "GROUP_CONSOLIDATED", "NAMED_SUBSIDIARIES",
                              "NAMED_DIVISION"])
    countries = c5.text_input("In-scope countries * (comma separated)",
                              ",".join(case.get("in_scope_countries") or []))
    layers = c6.multiselect("In-scope cost layers *", ["L0", "L1", "L2", "L3", "L4", "OPS"],
                            case.get("in_scope_cost_layers") or ["L0", "L2", "L4", "OPS"])

    c7, c8, c9 = st.columns(3)
    families = c7.text_input("In-scope service families *",
                             ",".join(case.get("in_scope_service_families") or ["WAN", "SSE"]))
    currency = c8.text_input("Base currency *", case.get("base_currency") or "USD", max_chars=3)
    price_year = c9.number_input("Price year *", 2020, 2035, case.get("price_year") or 2026)

    c10, c11, c12 = st.columns(3)
    horizon = c10.number_input("Analysis horizon (years) *", 1, 10,
                               case.get("analysis_horizon_years") or 5)
    drs = c11.text_input("Discount rate set *", case.get("discount_rate_set_id") or "DRS-2026-USD")
    contact = c12.selectbox("Client contact status *",
                            ["NO_CONTACT", "AWARE", "PARTICIPATING"])

    excluded = st.text_input("Known-but-excluded entities (comma separated)",
                             help="Stored explicitly, not merely omitted, so out-of-perimeter "
                                  "facts can be recognised and quarantined")

    if st.form_submit_button("Save intake block"):
        st.info("Intake fields are validated at pre-flight. Resolve the entity below.")

st.divider()
st.subheader("Subject-entity resolution")
st.caption("The system proposes; you dispose. Auto-selection is prohibited even when "
           "only one candidate is returned.")

col1, col2 = st.columns([3, 1])
hint = col1.text_input("Name as supplied", name or "")
provider = col2.selectbox("Provider", ["anthropic", "openai"])

if st.button("Generate candidates (LIVE agent run)", type="primary", disabled=not hint):
    with st.spinner("Calling provider..."):
        r = api.post(f"/v1/outside-in/cases/{case_id}/entities:resolve",
                     {"name_hint": hint, "identifier_hint": ident or None,
                      "provider": provider, "mode": "LIVE"})
    if "_error" in r:
        st.error(f"**Run failed closed.** {r['_error']}")
        st.caption("No candidates were fabricated. This is the intended behaviour when a "
                   "provider is unavailable (7.2B).")
    else:
        p = r["provenance"]
        st.success(f"{len(r['candidates'])} candidates. Provider response "
                   f"`{p['provider_response_id']}` - {p['input_tokens']} in / "
                   f"{p['output_tokens']} out tokens, {p['latency_ms']} ms.")

cands = api.get(f"/v1/outside-in/cases/{case_id}/entity-candidates").get("candidates", [])
if cands:
    st.markdown("**Candidates** - review the differentiators before confirming.")
    for c in cands:
        with st.expander(f"{c['legal_name']} ({c['domicile'] or '??'}) - "
                         f"match {c['match_score']}"):
            st.write({k: c[k] for k in ("identifier", "industry", "revenue", "employees",
                                        "group_parent", "website")})
            st.caption((c.get("sources") or {}).get("differentiator") or "")
            who = st.text_input("Confirmed by (your name)", key=f"who_{c['candidate_id']}")
            if st.button("Confirm this entity", key=f"cf_{c['candidate_id']}", disabled=not who):
                r = api.post(f"/v1/outside-in/cases/{case_id}:confirm-entity",
                             {"candidate_id": c["candidate_id"], "confirmed_by": who,
                              "group_perimeter": perimeter,
                              "excluded_entities": [x.strip() for x in excluded.split(",") if x.strip()]})
                if "_error" in r:
                    st.error(r["_error"])
                else:
                    st.success(f"Confirmed {r['legal_name']} - perimeter v{r['perimeter_version']}")
                    st.rerun()

if case.get("resolved_entity_id"):
    st.success(f"**Resolved:** {case['subject_entity_legal_name']} - confirmed by "
               f"{case['entity_confirmed_by']}, perimeter v{case['perimeter_version']}")
