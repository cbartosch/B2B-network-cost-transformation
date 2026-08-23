import streamlit as st

import api_client as api

st.set_page_config(page_title="Network Cost Transformation Workbench",
                   page_icon="||", layout="wide")

st.title("Enterprise Network Cost Transformation Workbench")
st.caption("Stage 0 outside-in estimator - specification v4.7 vertical slice")

health = api.get("/v1/health", deep=True)
if "_error" in health:
    st.error(f"API not reachable: {health['_error']}")
    st.stop()

auth_problem = api.probe_auth(health)
if auth_problem:
    st.error(f"**Authentication misconfigured.** {auth_problem}")
    st.caption("`/v1/health` is exempt from the token, which is why this page loads "
               "while everything else fails. Fix the mismatch before continuing.")
    st.stop()

providers = health.get("providers", {})
configured = [k for k, v in providers.items() if v]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Environment", health["environment"])
c2.metric("Providers configured", len(configured) or 0)
c3.metric("Schema", f"v{(health.get('schema') or {}).get('found', '?')}",
          "up to date" if (health.get("schema") or {}).get("up_to_date") else "drift",
          delta_color="off")
c4.metric("Auth", "enforced" if health.get("auth_required") else "open",
          delta_color="off")

if not configured:
    st.warning(
        "**No provider configured.** LIVE agent runs will fail closed rather than "
        "returning canned output. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env` "
        "and restart. This is the specification's fail-closed rule (7.2B), not a bug.")
else:
    st.success(f"Provider adapters configured: {', '.join(configured)}. "
               f"LIVE runs will make real API calls and record the provider response ID, "
               f"request timestamp and token usage as liveness proof (7.2C).")

st.divider()
st.subheader("Stage 0 sequence")
st.markdown("""
The workflow is deliberately ordered. Each step gates the next, and V0 cannot execute
until the first three are complete.

| Step | Page | Gate |
|---|---|---|
| 1 | **Intake and entity resolution** | Subject entity confirmed by a named user (0.1A) |
| 2 | **Known facts** | Attributed, rights-checked, corroborated where publicly verifiable (0.1B) |
| 3 | **Pre-flight** | Every BLOCK condition cleared and the report acknowledged (0.1C) |
| 4 | **Simulation** | Seeded topology; reproducible from one pinned integer (0.3B) |
| 5 | **Domain dispositions** | All 24 input domains disposed (0.3A) |
| 6 | **Run V0** | Coverage gate; COMPLETE, PARTIAL or refused (0.3C) |
| 7 | **Execution integrity** | Provider provenance for every agent run (7.2C) |

Use the sidebar to move between pages. Create or select a case below.
""")

st.divider()
st.subheader("Cases")
cases = api.get("/v1/outside-in/cases").get("cases", [])
if cases:
    labels = {f"{c['subject_entity_legal_name'] or '(unresolved)'} - {c['case_id'][:8]}":
              c["case_id"] for c in cases}
    pick = st.selectbox("Active case", list(labels))
    st.session_state["case_id"] = labels[pick]
    st.caption(f"Active case: `{labels[pick]}`")
else:
    st.info("No cases yet. Create one to begin.")

with st.form("new_case"):
    st.markdown("**New case**")
    a, b = st.columns(2)
    created_by = a.text_input("Your name", help="Used for named confirmation and audit")
    purpose = b.selectbox("Engagement purpose",
                          ["PRE_OUTREACH", "PROPOSAL_QUALIFICATION", "ACTIVE_ENGAGEMENT"])
    if st.form_submit_button("Create case") and created_by:
        r = api.post("/v1/outside-in/cases",
                     {"created_by": created_by, "engagement_purpose": purpose})
        if "_error" in r:
            st.error(r["_error"])
        else:
            st.session_state["case_id"] = r["case_id"]
            st.success(f"Case created: {r['case_id']}")
            st.rerun()
