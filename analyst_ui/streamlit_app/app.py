import streamlit as st

import api_client as api

st.set_page_config(page_title="Network Cost Transformation Workbench",
                   page_icon="🔎", layout="wide")

st.title("Enterprise Network Cost Transformation Workbench")

health = api.get("/v1/health", deep=True)
if "_error" in health:
    st.error(f"API not reachable: {health['_error']}")
    st.stop()

# Read the build from the running service rather than hardcoding it. The
# caption said "v4.7 vertical slice" for thirteen builds after that stopped
# being true - the same staleness /v1/health itself was carrying.
st.caption(f"Stage 0 outside-in estimator · build {health.get('build', '?')} · "
           f"{health.get('environment', '?')}")

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
        "and restart. This is the specification's fail-closed rule (7.2B), not a bug. "
        "Deterministic paths (savings recommendation, questionnaire prefill) still run.")
else:
    st.success(f"Provider adapters configured: {', '.join(configured)}. "
               f"LIVE runs will make real API calls and record the provider response ID, "
               f"request timestamp and token usage as liveness proof (7.2C).")

st.divider()

# ---------------------------------------------------------------- case picker
st.subheader("Case")
cases = api.get("/v1/outside-in/cases").get("cases", [])
case_id = None
if cases:
    labels = {f"{c['subject_entity_legal_name'] or '(unresolved)'} · {c['case_id'][:8]}":
              c["case_id"] for c in cases}
    pick = st.selectbox("Active case", list(labels),
                        help="Every page below operates on this case.")
    case_id = labels[pick]
    st.session_state["case_id"] = case_id

    with st.expander("Remove this case"):
        st.caption("Archiving takes a case out of this picker and keeps "
                   "everything. Deleting is for a case that is not a record of "
                   "anything - a typo, a duplicate, a scratch case - and is "
                   "refused once an estimate has been published, because that "
                   "snapshot is the provenance for a number that may have left "
                   "the building.")
        who = st.text_input("Acting as", key="rm_who")
        a, b = st.columns(2)
        if a.button("Archive", disabled=not who.strip()):
            r = api.post(f"/v1/outside-in/cases/{case_id}:archive"
                         f"?archived_by={who}&archived=true", {})
            if "_error" in r:
                st.error(r["_error"])
            else:
                st.success("Archived.")
                st.session_state.pop("case_id", None)
                st.rerun()
        confirm = b.checkbox("I understand this cannot be undone",
                             key="rm_confirm")
        if b.button("Delete permanently",
                    disabled=not (who.strip() and confirm)):
            r = api.delete(f"/v1/outside-in/cases/{case_id}",
                           deleted_by=who, force=True)
            if "_error" in r:
                st.error(r["_error"])
            else:
                st.success(f"Deleted. Removed: "
                           f"{r.get('removed') or 'nothing else'}")
                st.session_state.pop("case_id", None)
                st.rerun()
else:
    st.info("No cases yet. Create one below to begin.")

with st.expander("Create a new case", expanded=not cases):
    with st.form("new_case"):
        a, b = st.columns(2)
        created_by = a.text_input(
            "Your name", help="Recorded for named confirmation and audit. Not a role "
                              "or a team - a person.")
        entity = b.text_input(
            "Subject entity (legal name)",
            help="Optional here; entity resolution on page 1 confirms it properly.")
        c, d = st.columns(2)
        purpose = c.selectbox("Engagement purpose",
                              ["PRE_OUTREACH", "PROPOSAL_QUALIFICATION",
                               "ACTIVE_ENGAGEMENT"])
        country = d.text_input("Country of domicile", value="",
                               max_chars=2, help="ISO 3166-1 alpha-2, e.g. GB")
        submitted = st.form_submit_button("Create case", type="primary")
        if submitted:
            if not created_by.strip():
                st.error("Your name is required - an unattributed case cannot be audited.")
            else:
                body = {"created_by": created_by.strip(), "engagement_purpose": purpose}
                if entity.strip():
                    body["subject_entity_legal_name"] = entity.strip()
                if country.strip():
                    body["country_of_domicile"] = country.strip().upper()
                r = api.post("/v1/outside-in/cases", body)
                if "_error" in r:
                    st.error(r["_error"])
                else:
                    st.session_state["case_id"] = r["case_id"]
                    st.success(f"Case created: {r['case_id']}")
                    st.rerun()

# ---------------------------------------------------------------- progress
STEPS = [
    ("1", "Intake and entity resolution", "Subject entity confirmed by a named user (0.1A)"),
    ("2", "Known facts", "Attributed, rights-checked, corroborated where verifiable (0.1B)"),
    ("3", "Pre-flight", "Every BLOCK condition cleared and acknowledged (0.1C)"),
    ("4", "Simulation", "Seeded topology, reproducible from one pinned integer (0.3B)"),
    ("5", "Domain dispositions", "All 24 input domains disposed (0.3A)"),
    ("6", "Run V0", "Coverage gate: COMPLETE, PARTIAL or refused (0.3C)"),
    ("8", "Savings recommendation", "LLM-07 proposes, the Decimal engine decides (10/11)"),
    ("9", "V1 questionnaire and stage", "Client answers mapped, then advance to V1"),
    ("7", "Execution integrity", "Provider provenance for every agent run (7.2C)"),
]


def _progress(cid):
    """Where this case actually stands. Every value is read from the API, so a
    step shows done only when the service says it is - not when the interface
    guesses from what the user last clicked."""
    out = {}
    case = api.get(f"/v1/outside-in/cases/{cid}")
    out["case"] = case if "_error" not in case else {}
    out["entity_done"] = bool(out["case"].get("entity_confirmed_by"))
    out["stage"] = out["case"].get("stage") or "V0"

    facts = api.get(f"/v1/outside-in/cases/{cid}/known-facts")
    out["facts_n"] = len(facts.get("known_facts", []) if isinstance(facts, dict) else [])

    disp = api.get(f"/v1/outside-in/cases/{cid}/domain-dispositions")
    out["disposed"] = 0 if "_error" in disp else len(disp.get("dispositions", []))
    out["disp_blockers"] = len(disp.get("publication_blockers", []) or [])

    sims = api.get(f"/v1/outside-in/cases/{cid}/simulations")
    out["sims_n"] = len(sims.get("runs", []) if isinstance(sims, dict) else [])

    ests = api.get(f"/v1/outside-in/cases/{cid}/estimates")
    snaps = ests.get("snapshots", []) if isinstance(ests, dict) else []
    out["estimates_n"] = len(snaps)
    out["v0_status"] = snaps[0].get("v0_status") if snaps else None

    recs = api.get(f"/v1/outside-in/cases/{cid}/recommendations")
    out["recs_n"] = len(recs.get("recommendations", []) if isinstance(recs, dict) else [])

    q = api.get(f"/v1/outside-in/cases/{cid}/questionnaire")
    out["q_answered"] = q.get("answered", 0) if isinstance(q, dict) else 0
    out["q_total"] = q.get("total", 0) if isinstance(q, dict) else 0
    return out


if case_id:
    st.divider()
    head, badge = st.columns([4, 1])
    head.subheader("Where this case stands")
    p = _progress(case_id)
    badge.metric("Stage", p["stage"])

    done = "✅"; part = "🟡"; todo = "⬜"

    def _row(step, page, gate, mark, detail):
        return {"": mark, "Step": step, "Page": page, "Status": detail, "Gate": gate}

    rows = [
        _row("1", "Intake and entity resolution", STEPS[0][2],
             done if p["entity_done"] else todo,
             f"confirmed by {p['case'].get('entity_confirmed_by')}"
             if p["entity_done"] else "entity not confirmed"),
        _row("2", "Known facts", STEPS[1][2],
             done if p["facts_n"] else todo,
             f"{p['facts_n']} recorded" if p["facts_n"] else "none recorded (optional)"),
        _row("3", "Pre-flight", STEPS[2][2],
             done if p["entity_done"] else todo,
             "run it on page 3 before simulating"),
        _row("4", "Simulation", STEPS[3][2],
             done if p["sims_n"] else todo,
             f"{p['sims_n']} run(s)" if p["sims_n"] else "not run"),
        _row("5", "Domain dispositions", STEPS[4][2],
             done if p["disposed"] and not p["disp_blockers"]
             else part if p["disposed"] else todo,
             f"{p['disposed']}/24 disposed"
             + (f", {p['disp_blockers']} blocker(s)" if p["disp_blockers"] else "")),
        _row("6", "Run V0", STEPS[5][2],
             done if p["v0_status"] in ("COMPLETE", "PARTIAL") else todo,
             f"latest: {p['v0_status']}" if p["v0_status"] else "no estimate yet"),
        _row("8", "Savings recommendation", STEPS[6][2],
             done if p["recs_n"] else todo,
             f"{p['recs_n']} recommendation(s)" if p["recs_n"] else "none yet"),
        _row("9", "V1 questionnaire and stage", STEPS[7][2],
             done if p["q_total"] and p["q_answered"] == p["q_total"]
             else part if p["q_answered"] else todo,
             f"{p['q_answered']}/{p['q_total']} answered" if p["q_total"]
             else "questionnaire not created"),
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    nxt = next((r for r in rows if r[""] != done), None)
    if nxt:
        st.info(f"**Next:** step {nxt['Step']} — {nxt['Page']}. {nxt['Gate']}")
    else:
        st.success("Every Stage 0 step is complete for this case.")

st.divider()
with st.expander("How the workflow is ordered, and why"):
    st.markdown("""
The sequence is a chain of gates, not a menu. Each step refuses until the one before it
is satisfied, and each refusal names the condition that is open rather than failing
generically.

* **Entity before evidence.** Researching an entity you have not resolved produces
  confident findings about the wrong company.
* **Pre-flight before execution.** A blocked pre-flight stops a simulation; there is no
  "run anyway".
* **Dispositions before publication.** All 24 input domains must be disposed — evidenced,
  client-confirmed, benchmark, simulated or explicitly declared unknown. An unstated
  domain blocks publication rather than silently defaulting.
* **Coverage before a number.** V0 publishes COMPLETE, PARTIAL, or refuses. It never
  publishes a figure it cannot support.

Use the sidebar to move between pages. The table above reflects live service state, not
what this interface remembers.
""")
