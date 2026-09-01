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
                   "domain takes minutes rather than seconds. Each result "
                   "appears below as it lands.")
        # Results render inside the loop, not after it. A run is fifteen to
        # twenty minutes and reported nothing until the last domain finished -
        # so a domain that found four sourced quantities and one that abstained
        # were indistinguishable for a quarter of an hour, and there was no
        # reason to keep watching. Streamlit flushes as the script runs, so
        # writing per domain is enough.
        log = st.container()
        tally = {"resolved": 0, "declared_unknown": 0, "failed": 0}
        lines = []
        started = time.monotonic()

        for i, d in enumerate(pending, start=1):
            status.write(f"({i}/{len(pending)}) {d['domain_no']}. "
                         f"{d['domain_name']} - {d['agent_id']} "
                         f"[{int(time.monotonic() - started)}s elapsed]")
            _t0 = time.monotonic()
            r = api.post(f"/v1/outside-in/cases/{case_id}/domain-research:run",
                         {"overwrite": overwrite, "domain_nos": [d["domain_no"]]},
                         timeout=600.0)
            _secs = int(time.monotonic() - _t0)
            _head = f"{d['domain_no']}. {d['domain_name']}"

            if "_error" in r:
                # Keep going. One domain failing is not a reason to abandon the
                # other sixteen, and what succeeded is already persisted.
                _line = ("error", f"{_head} - could not be attempted "
                                  f"({_secs}s): {r['_error']}")
            else:
                for k in tally:
                    tally[k] += r.get(k, 0)
                _res = (r.get("results") or [{}])[0]
                _disp = _res.get("disposition") or "no disposition"
                _tri = _res.get("triangulated") or []
                _qty = _res.get("quantities") or []
                _srcs = _res.get("verified_source_count") or 0
                _rel = _res.get("reliability") or {}
                _bits = [f"{_rel.get('grade') or _disp}"]
                if _res.get("reason"):
                    _bits.append(_res["reason"])
                if _srcs:
                    _bits.append(f"{_srcs} verified source(s)")
                if _qty:
                    _bits.append(f"{len(_qty)} quantity(ies)")
                if _res.get("budget_note"):
                    _bits.append(_res["budget_note"])
                if _res.get("failure_detail"):
                    _bits.append(_res["failure_detail"])
                # Findings kept from a run that did not reach a disposition.
                # Not evidence, and worth seeing: a domain refused for citing
                # two sources when three were needed still found two.
                if _rel.get("shortfalls"):
                    _bits.append("short of the bar: "
                                 + "; ".join(_rel["shortfalls"][:2]))
                if _res.get("qualitative"):
                    _bits.append(f"{len(_res['qualitative'])} qualitative "
                                 f"finding(s) kept")
                # Coloured by grade, not by disposition: a RELIABLE finding is
                # a result worth reading, and painting it the same as "found
                # nothing" was the display half of discarding it.
                _kind = ("success" if _rel.get("grade") == "VERY_RELIABLE"
                         else "error" if _res.get("failed")
                         else "info")
                _line = (_kind, f"{_head} - " + "; ".join(_bits) + f" ({_secs}s)")

                # The numbers, as they land. A band with a spread is the part
                # worth seeing while the run is still going, because it decides
                # whether the next domain is worth waiting for.
                for _t in _tri:
                    if _t.get("base") is not None:
                        _flags = ", ".join(_t.get("flags") or [])
                        lines.append((
                            "detail",
                            f"    {_t.get('label')} {_t.get('country') or ''}: "
                            f"{_t.get('low')} / {_t.get('base')} / {_t.get('high')}"
                            f" from {_t.get('candidate_count')} source(s)"
                            + (f"  [{_flags}]" if _flags else "")))

            # The headline goes before the band detail collected above it, so
            # the log reads in the order the analyst thinks: domain, then its
            # numbers.
            _details = []
            while lines and lines[-1][0] == "detail":
                _details.insert(0, lines.pop())
            lines.append(_line)
            lines.extend(_details)

            with log:
                {"success": st.success, "error": st.error,
                 "info": st.info}.get(_line[0], st.write)(_line[1])
                for _kind, _text in _details:
                    st.caption(_text)

            bar.progress(i / len(pending))

        status.empty()
        # Kept across the rerun that refreshes the disposition table, so the
        # per-domain log is still there afterwards rather than being replaced
        # by a one-line summary.
        st.session_state["_research_log"] = lines
        api.flash(
            f"{tally['resolved']} resolved, {tally['declared_unknown']} declared "
            f"unknown, {tally['failed']} failed (no disposition written for "
            f"those - a technical failure isn't evidence; see Execution "
            f"integrity).")
        st.rerun()

_prev = st.session_state.get("_research_log")
if _prev:
    with st.expander(f"Last research run - {len(_prev)} line(s)", expanded=True):
        for _kind, _text in _prev:
            if _kind == "detail":
                st.caption(_text)
            else:
                {"success": st.success, "error": st.error,
                 "info": st.info}.get(_kind, st.write)(_text)
        if st.button("Clear this log"):
            st.session_state.pop("_research_log", None)
            st.rerun()

with st.expander("Review research findings and promote them into the estimate"):
    # Streamlit runs an expander body whether or not it is open, so an
    # unconditional fetch here cost a round trip on every interaction
    # with this page - including every keystroke in the editor below.
    if st.checkbox("Load findings", key="load_findings"):
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
            ar = _f.get("archetype_candidates", [])
            an = _f.get("anchor_candidates", [])
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
            if ar:
                # These reach the simulation's topology rather than its counts:
                # a product pair, a dual-access rate, a bandwidth, a headcount
                # per site. Until this list existed the finding was classified
                # and never offered, so it could not be promoted.
                st.markdown("**How a site type is built** (feeds the simulation "
                            "topology)")
                for c in ar:
                    q = c["quantity"]
                    _g = (c.get("reliability") or {}).get("grade", "")
                    if st.checkbox(
                            f"{q.get('label')}: {q.get('value')} "
                            f"{q.get('unit')} - domain {c['domain_no']}"
                            + (f" [{_g}]" if _g else ""),
                            key=f"ar_{c['candidate_id']}"):
                        chosen.append(c["candidate_id"])
            if an:
                st.markdown("**Disclosed cost line** (the ANCHOR method's "
                            "anchor)")
                st.caption("Promoted as evidence, so the anchor reports "
                           "EVIDENCED_PUBLIC instead of being retyped on page "
                           "6 as an assertion that caps the estimate at 0.50.")
                for c in an:
                    q = c["quantity"]
                    if st.checkbox(
                            f"{q.get('label')}: {q.get('value')} "
                            f"{q.get('unit')} - domain {c['domain_no']}",
                            key=f"an_{c['candidate_id']}"):
                        chosen.append(c["candidate_id"])
            if un:
                st.caption(f"{len(un)} finding(s) are not in a shape this model "
                           f"consumes. They are not rejected - they stay as "
                           f"evidence on their domain.")
            if not (fp or pr or ar or an or un):
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
                        f"{len(r['promoted_footprint'])} footprint row(s), "
                        f"{len(r.get('promoted_archetype') or [])} topology "
                        f"field(s), {len(r.get('promoted_anchor') or [])} "
                        f"anchor(s) promoted; "
                        f"{len(r['proposed_prices'])} price(s) proposed "
                        f"unapproved.")
                    for _a in r.get("promoted_archetype") or []:
                        st.caption(f"   topology: {_a['archetype']}."
                                   f"{_a['field']} = {_a['value']} "
                                   f"(domain {_a['domain_no']})")
                    for _a in r.get("promoted_anchor") or []:
                        st.caption(f"   anchor: {_a['label']} = {_a['value']} "
                                   f"(domain {_a['domain_no']})")
                    for px in r.get("proposed_prices", []):
                        cx = px.get("benchmark_comparison") or {}
                        line = (f"{px['country']} {px['product']} @ "
                                f"{px['base']}: {cx.get('note', '')}")
                        if cx.get("material"):
                            st.error("Materially disagrees with the approved "
                                     "benchmark - " + line)
                        elif cx.get("verdict") == "NO_BENCHMARK":
                            st.info(line)
                        else:
                            st.caption(line)
                    if r.get("material_divergences"):
                        st.warning(
                            "Public research and a governed benchmark disagree "
                            "materially above. Both are unapproved and neither "
                            "is in any estimate. A steward should decide which "
                            "is right before approving either - the "
                            "disagreement is the finding.")
                    st.rerun()

            for _label, _key, _cols in (
                    ("topology fields", "already_promoted_archetype",
                     ["archetype", "field", "value", "origin",
                      "reliability_grade", "recorded_by"]),
                    ("anchors", "already_promoted_anchor",
                     ["label", "value", "currency", "reliability_grade",
                      "promoted_by"])):
                _rows = _f.get(_key) or []
                if _rows:
                    st.caption(f"Already promoted {_label}:")
                    st.dataframe(pd.DataFrame(_rows)[
                        [c for c in _cols if c in _rows[0]]],
                        use_container_width=True, hide_index=True)

            already = _f.get("already_promoted_footprint", [])
            if already:
                st.caption("Already promoted:")
                st.dataframe(pd.DataFrame(already)[
                    ["country", "archetype", "sites", "as_of", "promoted_by"]],
                    use_container_width=True, hide_index=True)

    else:
        st.caption("Tick to load researched quantities for this case.")

with st.expander("Show the prompt used for a domain"):
    if st.checkbox("Load prompt viewer", key="load_prompt"):
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

    else:
        st.caption("Tick to build and show the prompt for a domain.")
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

st.subheader("What research actually found")
st.caption("The table below records a disposition and a reason. Everything the "
           "research produced behind that - the sources, the fetched fragments, "
           "the numbers, and which budget ran out where nothing was found - is "
           "stored on each domain and shown here. A disposition without its "
           "evidence is an assertion.")

_researched = [d for d in current.get("dispositions", [])
               if (d.get("evidence") or d.get("agent_run_id"))]
if not _researched:
    st.caption("No researched domains on this case yet.")
else:
    _names = dict(catalogue)
    for d in sorted(_researched, key=lambda d: d["domain_no"]):
        ev = d.get("evidence") or {}
        srcs = ev.get("sources") or []
        qty = ev.get("quantities") or []
        head = (f"{d['domain_no']}. {_names.get(d['domain_no'], '')} - "
                f"{d.get('disposition')}"
                + (f" ({d.get('reason')})" if d.get("reason") else "")
                + (f" - {len(srcs)} source(s), {len(qty)} quantity(ies)"
                   if (srcs or qty) else ""))
        with st.expander(head):
            if ev.get("budget_note"):
                st.warning(f"Stopped early: {ev['budget_note']}")
            tri = ev.get("triangulated") or []
            if tri:
                st.markdown("**Triangulated bands**")
                st.dataframe(pd.DataFrame([{
                    "label": t.get("label"), "country": t.get("country"),
                    "low": t.get("low"), "base": t.get("base"),
                    "high": t.get("high"),
                    "sources": t.get("candidate_count"),
                    "spread": (f"{t['spread_share']:.0%}"
                               if t.get("spread_share") is not None else ""),
                    "vintage": f"{t.get('oldest_year') or '?'}-"
                               f"{t.get('newest_year') or '?'}",
                    "flags": ", ".join(t.get("flags") or []),
                } for t in tri]), use_container_width=True, hide_index=True)
                st.caption("low and high are the observed extremes, not a "
                           "confidence interval. base is the median.")
            for c in ev.get("conflicts") or []:
                st.warning(f"**{c['label']} {c.get('country') or ''}** - "
                           f"{c['why']}")
                st.dataframe(pd.DataFrame(c.get("candidates") or []),
                             use_container_width=True, hide_index=True)
            if qty:
                st.markdown("**Numbers as the agent reported them**")
                st.dataframe(pd.DataFrame(qty), use_container_width=True,
                             hide_index=True)
            else:
                st.caption("No structured quantities - the finding was "
                           "qualitative, or the agent returned prose only.")
            if srcs:
                st.markdown("**Sources, as independently re-fetched**")
                for srec in srcs:
                    st.write(f"- {srec.get('publisher') or 'source'}: "
                             f"{srec.get('url')}")
                    if srec.get("fragment"):
                        st.caption(srec["fragment"][:400])
            if d.get("agent_run_id"):
                st.caption(f"agent_run_id `{d['agent_run_id']}` - the provider "
                           f"call and its liveness proof are on page 7.")

st.divider()
st.subheader("Dispositions")

edited = st.data_editor(
    pd.DataFrame(rows), use_container_width=True, hide_index=True, height=520,
    column_config={
        "domain_no": st.column_config.NumberColumn("#", disabled=True, width="small"),
        "domain_name": st.column_config.TextColumn("Input domain", disabled=True, width="large"),
        "disposition": st.column_config.SelectboxColumn("Disposition", options=DISPOSITIONS),
        "reason": st.column_config.SelectboxColumn("Reason (DECLARED_UNKNOWN only)",
                                                   options=REASONS)})

# Streamlit discards an edited table on a page switch, so an unsaved change to
# 24 dispositions is lost silently. Warned rather than auto-saved: a
# disposition is a statement about evidence and writing 24 of them because
# somebody scrolled would be worse than losing them.
_changed = [r for r, o in zip(edited.to_dict("records"), rows)
            if (r.get("disposition"), r.get("reason") or None)
            != (o.get("disposition"), o.get("reason") or None)]
if _changed:
    st.warning(
        f"**{len(_changed)} unsaved change(s).** Streamlit discards an edited "
        f"table when you switch page, so save before leaving: "
        + ", ".join(f"{r['domain_no']}. {r['domain_name']}"
                    for r in _changed[:4])
        + (" and others." if len(_changed) > 4 else ""))

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
