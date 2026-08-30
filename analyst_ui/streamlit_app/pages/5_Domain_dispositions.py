import pandas as pd
import streamlit as st
import api_client as api

st.title("5. Domain dispositions")
st.caption("Specification 0.3A - maximalist means every in-scope input domain carries a "
           "recorded disposition, not that the search ran longer.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

with st.expander("Run research (LLM-01 / LLM-08)"):
    st.caption("Populates whichever of the 24 domains these two agents cover (17 of 24 - "
               "see the README) and do not already carry a disposition. The other 7 stay "
               "manual by design. Never overwrites an existing disposition, from any "
               "source, unless the box below is checked.")
    overwrite = st.checkbox("Overwrite domains that already have a disposition", value=False)

    plan = api.get(f"/v1/outside-in/cases/{case_id}/domain-research:plan",
                   overwrite=overwrite)
    if "_error" in plan:
        st.error(plan["_error"])
        pending = []
    else:
        pending = plan.get("pending", [])
        st.caption(f"{len(pending)} domain(s) to research, "
                   f"{len(plan.get('skipped', []))} left alone.")

    if st.button("Run research now", type="primary", disabled=not pending):
        # One request per domain, not one for all 17. A full run is minutes of
        # LIVE provider calls and source fetches; a single synchronous request
        # for the lot exceeded the client timeout and reported "API
        # unreachable: timed out" - with no way to tell a slow run from a dead
        # one, and no sight of the domains that had already succeeded.
        #
        # Walking the list keeps every request short, shows progress, and is
        # resumable for free: a domain that already carries a disposition is
        # skipped by the endpoint, so re-running continues rather than starts
        # over.
        import time
        bar = st.progress(0.0)
        status = st.empty()
        st.caption("Each domain is a live provider call carrying a web search, "
                   "plus an independent fetch of every source it cites, so a "
                   "domain takes minutes rather than seconds. Progress below is "
                   "per domain - if it is moving, nothing is stuck.")
        tally = {"resolved": 0, "declared_unknown": 0, "failed": 0}
        problems = []
        started = time.monotonic()
        for i, d in enumerate(pending, start=1):
            status.write(f"({i}/{len(pending)}) {d['domain_no']}. "
                         f"{d['domain_name']} - {d['agent_id']} "
                         f"[{int(time.monotonic() - started)}s elapsed]")
            r = api.post(f"/v1/outside-in/cases/{case_id}/domain-research:run",
                         {"overwrite": overwrite, "domain_nos": [d["domain_no"]]},
                         timeout=600.0)
            if "_error" in r:
                # Keep going. One domain failing is not a reason to abandon the
                # other sixteen, and what succeeded is already persisted.
                problems.append(f"{d['domain_no']}. {d['domain_name']}: {r['_error']}")
            else:
                for k in tally:
                    tally[k] += r.get(k, 0)
            bar.progress(i / len(pending))
        status.empty()

        st.success(
            f"{tally['resolved']} resolved, {tally['declared_unknown']} declared "
            f"unknown, {tally['failed']} failed (no disposition written for those - "
            f"a technical failure isn't evidence; see Execution integrity).")
        if problems:
            st.warning("Some domains could not be attempted:")
            for line in problems:
                st.caption(line)
        st.rerun()

with st.expander("Review research findings and promote them into the estimate"):
    st.caption("Researched numbers only reach the estimate when a named person "
               "puts them there. Site counts land on the case as the evidenced "
               "footprint the simulation starts from. Prices are written "
               "UNAPPROVED and take no part in any estimate until a steward "
               "approves them - research proposes a governed value, it does "
               "not set one.")

    _f = api.get(f"/v1/outside-in/cases/{case_id}/research-findings")
    if "_error" in _f:
        st.error(_f["_error"])
    else:
        fp = _f.get("footprint_candidates", [])
        pr = _f.get("price_candidates", [])
        un = _f.get("unclassified", [])

        chosen = []
        if fp:
            st.markdown("**Site counts**")
            for c in fp:
                q = c["quantity"]
                if st.checkbox(
                        f"{q.get('country')} {q.get('label')}: {q.get('value')} "
                        f"sites (as of {q.get('as_of') or 'undated'}) "
                        f"- domain {c['domain_no']}",
                        key=f"fp_{c['candidate_id']}"):
                    chosen.append(c["candidate_id"])
        if pr:
            st.markdown("**Circuit prices** (promoted unapproved)")
            for c in pr:
                q = c["quantity"]
                if st.checkbox(
                        f"{q.get('country')} {q.get('label')}: {q.get('value')} "
                        f"{q.get('unit')} (as of {q.get('as_of') or 'undated'})",
                        key=f"pr_{c['candidate_id']}"):
                    chosen.append(c["candidate_id"])
        if un:
            st.caption(f"{len(un)} finding(s) are not in a shape this model "
                       f"consumes. They are not rejected - they stay as "
                       f"evidence on their domain.")
        if not (fp or pr or un):
            st.caption("No researched quantities on this case yet.")

        who = st.text_input("Promoting as (your name)", key="promote_who")
        if st.button("Promote selected", disabled=not (chosen and who)):
            r = api.post(
                f"/v1/outside-in/cases/{case_id}/research-findings:promote",
                {"candidate_ids": chosen, "promoted_by": who})
            if "_error" in r:
                st.error(r["_error"])
            else:
                st.success(
                    f"{len(r['promoted_footprint'])} footprint row(s) promoted, "
                    f"{len(r['proposed_prices'])} price(s) proposed unapproved.")
                st.rerun()

        already = _f.get("already_promoted_footprint", [])
        if already:
            st.caption("Already promoted:")
            st.dataframe(pd.DataFrame(already)[
                ["country", "archetype", "sites", "as_of", "promoted_by"]],
                use_container_width=True, hide_index=True)

with st.expander("Show the prompt used for a domain"):
    st.caption("Exactly what the agent is sent for one domain - system prompt, "
               "user prompt and search-tool configuration. Nothing runs; this "
               "builds the text and shows it. The brief inside it is the main "
               "lever on how good a domain's research is, so it is worth "
               "reading before concluding a domain has no public evidence.")

    _cat = api.get(f"/v1/outside-in/cases/{case_id}/domain-research:plan",
                   overwrite=True)
    _choices = ([] if "_error" in _cat else
                sorted(_cat.get("pending", []) + _cat.get("skipped", []),
                       key=lambda d: d["domain_no"]))
    if not _choices:
        st.caption("No researchable domains to show.")
    else:
        pick = st.selectbox(
            "Domain", _choices,
            format_func=lambda d: f"{d['domain_no']}. {d['domain_name']} "
                                  f"({d['agent_id']})")
        p = api.get(f"/v1/outside-in/cases/{case_id}/domain-research:prompt",
                    domain_no=pick["domain_no"])
        if "_error" in p:
            st.error(p["_error"])
        elif not p.get("researchable"):
            st.info(p.get("note"))
        else:
            match = p.get("matches_last_run")
            if match is True:
                st.success("This is the exact text the last run for this domain "
                           "used - the request hash matches what the gateway "
                           "recorded.")
            elif match is False:
                st.warning("The brief or the case scope has changed since this "
                           "domain was last researched, so the stored result "
                           "came from different text than the one below. "
                           "Re-run before comparing them.")
            else:
                st.caption("This domain has not been researched yet, so there is "
                           "no recorded prompt to compare against.")

            st.markdown("**Brief for this domain**")
            st.info(p.get("brief") or "No brief - the agent gets the bare "
                                      "domain name, which is the condition that "
                                      "produces vague results.")
            st.markdown("**System prompt**")
            st.code(p["system"], language="text")
            st.markdown("**User prompt**")
            st.code(p["prompt"], language="text")
            st.markdown("**Search tool**")
            st.json(p["tools"])
            st.caption(f"request_hash `{p['request_hash']}` - "
                       f"{p['hash_note']}")

st.divider()
current = api.get(f"/v1/outside-in/cases/{case_id}/domain-dispositions")
catalogue = current.get("catalogue", [])
existing = {d["domain_no"]: d for d in current.get("dispositions", [])}

DISPOSITIONS = ["EVIDENCED_PUBLIC", "DERIVED_PUBLIC", "CLIENT_CONFIRMED",
                "BENCHMARK_PRIOR", "ANALYST_ASSERTED_PRIOR", "SIMULATED",
                "DECLARED_UNKNOWN"]
REASONS = ["", "NO_PUBLIC_EVIDENCE", "BUDGET_EXHAUSTED", "OUT_OF_PERIMETER",
           "CONFLICTING_EVIDENCE_UNRESOLVED", "NOT_APPLICABLE"]

rows = [{"domain_no": n, "domain_name": nm,
         "disposition": existing.get(n, {}).get("disposition", "BENCHMARK_PRIOR"),
         "reason": existing.get(n, {}).get("reason") or ""} for n, nm in catalogue]

edited = st.data_editor(
    pd.DataFrame(rows), use_container_width=True, hide_index=True, height=520,
    column_config={
        "domain_no": st.column_config.NumberColumn("#", disabled=True, width="small"),
        "domain_name": st.column_config.TextColumn("Input domain", disabled=True, width="large"),
        "disposition": st.column_config.SelectboxColumn("Disposition", options=DISPOSITIONS),
        "reason": st.column_config.SelectboxColumn("Reason (DECLARED_UNKNOWN only)",
                                                   options=REASONS)})

if st.button("Save dispositions", type="primary"):
    payload = [{"domain_no": int(r["domain_no"]), "domain_name": r["domain_name"],
                "disposition": r["disposition"], "reason": r["reason"] or None}
               for r in edited.to_dict("records")]
    r = api.put(f"/v1/outside-in/cases/{case_id}/domain-dispositions", payload)
    if "_error" in r:
        st.error(r["_error"])
    elif r["publication_blockers"]:
        st.warning("Saved, but V0 cannot publish:")
        for b in r["publication_blockers"]:
            st.write(f"- {b}")
    else:
        s = r["summary"]
        st.success(f"All {s['total_domains']} domains disposed. "
                   f"{s['declared_unknown']} declared unknown.")
        if s["budget_exhausted_domains"]:
            st.info(f"BUDGET_EXHAUSTED (recorded distinctly from searched-and-empty): "
                    f"{s['budget_exhausted_domains']}")
