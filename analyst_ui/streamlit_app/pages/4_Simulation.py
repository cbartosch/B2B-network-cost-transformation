import time

import pandas as pd
import streamlit as st
import api_client as api

st.title("4. Topology and architecture simulation")
st.caption("Specification 0.3B - a sizing instrument, not evidence. Never written to "
           "the topology graph; diversity state is always SIMULATED.")

case_id = st.session_state.get("case_id")
# Session state outlives a case switch, so anything cached here must be scoped
# to the case it came from or it will be rendered under the wrong one.
_scope = st.session_state.get("_scoped_case")
if _scope != case_id:
    for _k in ['sim_run_id', 'sim']:
        st.session_state.pop(_k, None)
    st.session_state["_scoped_case"] = case_id
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

st.info("Simulated structure can never set EVIDENCED, never supports a resilience-dependent "
        "lever, and is permanently barred from benchmark promotion (5.6).")

st.subheader("Footprint")
# Start from promoted research where it exists. Until Tier 3 this editor
# always opened on four hardcoded demo rows, so a case whose footprint had
# actually been researched still simulated GB/DE/US placeholders unless
# someone retyped the findings by hand - which is the shape "the research
# changes nothing" took in practice.
# One call. The precedence - promoted research, then a saved footprint, then
# a registered known fact, then a placeholder - is resolved server-side in
# domain/footprint.py, where it can be tested. It lived here as four branches
# and was wrong in a different way four times running.
_fp = api.get(f"/v1/outside-in/cases/{case_id}/footprint")

st.markdown("**Known sites by type**")
if "_error" in _fp:
    st.error(f"**Could not resolve the footprint.** {_fp['_error']}")
    st.warning("The table below is empty. Fix the error above rather than "
               "typing over it - an estimate built on whatever appears here "
               "would look deliberate.")
    _resolved, _origin, _detail = [], "ERROR", ""
else:
    _resolved = _fp.get("footprint") or []
    _origin = _fp.get("origin", "")
    _detail = _fp.get("detail", "")

    _labels = {
        "PROMOTED_RESEARCH": ("Promoted from research", st.success),
        "ANALYST_SAVED": ("Saved on this case", st.info),
        "KNOWN_FACT": ("Derived from the known-facts register", st.info),
        "SCOPE_PLACEHOLDER": ("Placeholder", st.warning),
        "ILLUSTRATIVE": ("Illustrative", st.warning),
    }
    _title, _render = _labels.get(_origin, (_origin, st.info))
    _total = sum(int(r.get("sites") or 0) for r in _resolved)
    _render(f"**{_title}** - {_total:,} site(s) across "
            f"{len({r.get('country') for r in _resolved})} country(ies). "
            f"{_detail}")

    if _fp.get("needs_split"):
        st.warning(_fp.get("split_note", ""))

    if _resolved:
        st.dataframe(pd.DataFrame([{
            "country": r.get("country"), "type": r.get("archetype"),
            "sites": r.get("sites")} for r in _resolved]),
            use_container_width=True, hide_index=True)

    if _origin == "ANALYST_SAVED":
        # A saved footprint outranks the register, which is right when it was
        # a decision and wrong when it was left over. Removing it should not
        # require finding an endpoint.
        if st.button("Discard the saved footprint and use the register instead"):
            _c = api.put(f"/v1/outside-in/cases/{case_id}",
                         {"analyst_footprint": []})
            if "_error" in _c:
                st.error(_c["_error"])
            else:
                st.rerun()

    if _origin == "PROMOTED_RESEARCH":
        with st.expander("Sources behind these counts"):
            for r in _fp.get("provenance") or []:
                st.markdown(f"**{r['country']} {r['archetype']}: {r['sites']}**")
                if r.get("band_low") is not None and r.get("band_high") is not None:
                    st.caption(f"   sources said {r['band_low']}-{r['band_high']} "
                               f"across {r.get('source_count') or '?'} source(s)")
                for url in r.get("source_urls") or []:
                    st.caption(f"   {url}")
    elif _origin in ("SCOPE_PLACEHOLDER", "ILLUSTRATIVE"):
        st.caption(
            "To replace these: research domain 2 and promote the counts on "
            "page 5, or register what you know on page 2 - a registered "
            "Location footprint fact is picked up here automatically.")

st.caption("Whatever is in the table below is what runs. Edit it, then Save or "
           "Run - both persist it to the case.")
default = pd.DataFrame(
    [{"country": r.get("country"), "archetype": r.get("archetype"),
      "sites": r.get("sites")} for r in _resolved]
    or [{"country": "", "archetype": "", "sites": 0}])

fp = st.data_editor(default, num_rows="dynamic", use_container_width=True)

c1, c2 = st.columns(2)
seed = c1.number_input("Seed", 0, 10**9, 42,
                       help="The whole ensemble is reproducible from this one integer")
size = c2.number_input("Ensemble size", 1, 200, 25)

ARCHETYPES = ("BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC", "STORE")


def _clean_footprint(frame):
    """Turn what the editor hands back into something the API can accept.

    The dynamic editor always shows a trailing blank row, and clicking into it
    is enough to put {"country": null, "archetype": null, "sites": null} in the
    payload - which fails schema validation with a message about string types
    that tells an analyst nothing about the row they half-filled. Rows that
    carry no country or archetype are dropped as what they are: an artefact of
    the widget, not an instruction.

    Everything else is reported rather than silently corrected, because a
    misspelled archetype is a typo the analyst can fix and a coerced one is a
    site type they did not choose.
    """
    def _text(value):
        # pandas turns an empty editor cell into NaN, and str(nan) is the
        # truthy string "nan" - so `value or ""` keeps it and the blank row
        # arrives as country "NAN". Checked explicitly rather than by
        # truthiness, which is the trap.
        if value is None or value != value:
            return ""
        return str(value).strip().upper()

    rows, problems = [], []
    for i, raw in enumerate(frame.to_dict("records"), start=1):
        country = _text(raw.get("country"))
        archetype = _text(raw.get("archetype"))
        if not country and not archetype:
            continue                      # the widget's blank row
        if not country or len(country) != 2:
            problems.append(f"row {i}: country {country or '(blank)'!r} is not "
                            f"a two-letter code")
            continue
        if archetype not in ARCHETYPES:
            problems.append(f"row {i}: archetype {archetype or '(blank)'!r} is "
                            f"not one of {', '.join(ARCHETYPES)}")
            continue
        sites = raw.get("sites")
        try:
            sites = int(sites) if sites is not None and sites == sites else 0
        except (TypeError, ValueError):
            problems.append(f"row {i}: sites {sites!r} is not a whole number")
            continue
        if sites < 0:
            problems.append(f"row {i}: sites cannot be negative")
            continue
        rows.append({"country": country, "archetype": archetype, "sites": sites})
    return rows, problems



_edited, _edit_problems = _clean_footprint(fp)
if not _edit_problems and _edited != [
        {"country": (r.get("country") or "").upper(),
         "archetype": (r.get("archetype") or "").upper(),
         "sites": int(r.get("sites") or 0)}
        for r in (_resolved or [])]:
    st.warning("**Unsaved changes.** Streamlit discards an edited table when "
               "you switch page, so Save or Run before leaving - otherwise "
               "these figures are gone and the page reopens on whatever the "
               "case last had.")

_save_col, _run_col = st.columns([1, 3])
if _save_col.button("Save footprint"):
    _rows_to_save, _problems = _clean_footprint(fp)
    for _m in _problems:
        st.error(_m)
    if not _problems:
        _r = api.put(f"/v1/outside-in/cases/{case_id}",
                     {"analyst_footprint": _rows_to_save})
        if "_error" in _r:
            st.error(_r["_error"])
        else:
            st.success(f"Saved {len(_rows_to_save)} row(s) to the case. They "
                       f"will be here next time without running anything.")
            st.rerun()

if _run_col.button("Run simulation", type="primary"):
    footprint, problems = _clean_footprint(fp)
    for message in problems:
        st.error(message)
    if not problems and not footprint:
        st.error("No usable rows. Give at least one country, archetype and "
                 "site count.")
    elif not problems:
        # Saved as well as run. Two separate acts meant an analyst could
        # edit, run, move to the next page and lose the edit - it lived in the
        # run's parameters and nowhere the case could see. Running a footprint
        # is a clear enough statement that you meant it.
        api.put(f"/v1/outside-in/cases/{case_id}",
                {"analyst_footprint": footprint})
        r = api.post(f"/v1/outside-in/cases/{case_id}/simulations:run",
                     {"seed": int(seed), "ensemble_size": int(size),
                      "footprint": footprint})
        if "_error" in r:
            st.error(r["_error"])
        else:
            st.session_state["sim_run_id"] = r["simulation_run_id"]
            st.session_state.pop("sim", None)
            st.rerun()

run_id = st.session_state.get("sim_run_id")
if run_id and "sim" not in st.session_state:
    state = api.get(f"/v1/outside-in/simulations/{run_id}", include_output=True)
    if "_error" in state:
        st.error(state["_error"])
    elif state["status"] in ("QUEUED", "RUNNING", "CANCELLING"):
        st.progress(min(1.0, (state["percent"] or 0) / 100),
                    text=f"{state['status']} - pass {state['completed']} of "
                         f"{state['total']} ({state['percent']}%)")
        c1, c2 = st.columns(2)
        if c1.button("Cancel"):
            api.post(f"/v1/outside-in/simulations/{run_id}:cancel")
            st.rerun()
        if c2.button("Refresh"):
            st.rerun()
        time.sleep(1.5)
        st.rerun()
    elif state["status"] == "CANCELLED":
        st.warning(f"Cancelled after {state['completed']} of {state['total']} passes. "
                   f"Completed passes are kept - resuming continues from there and "
                   f"produces the identical result.")
        if st.button("Resume"):
            r = api.post(f"/v1/outside-in/simulations/{run_id}:resume")
            if r.get("note"):
                st.info(r["note"])
            st.rerun()
    elif state["status"] == "FAILED":
        st.error(f"Failed: {state.get('error')}")
        if st.button("Resume from checkpoint"):
            r = api.post(f"/v1/outside-in/simulations/{run_id}:resume")
            if r.get("note"):
                st.info(r["note"])
            st.rerun()
    elif state["status"] == "SUCCEEDED":
        st.session_state["sim"] = {"simulation_run_id": run_id,
                                   "output_hash": state["output_hash"],
                                   "output": state["output"]}
        st.success(f"Run `{run_id[:8]}` - output hash `{state['output_hash'][:16]}...`")

sim = st.session_state.get("sim")
if sim:
    o = sim["output"]
    a, b, c, d = st.columns(4)
    a.metric("Sites", o["sites"])
    b.metric("Primary circuits", o["circuits_primary"]["base"],
             "deterministic from footprint", delta_color="off")
    c.metric("Backup circuits", o["circuits_backup"]["base"],
             f"{o['circuits_backup']['low']} - {o['circuits_backup']['high']} (simulated)",
             delta_color="off")
    d.metric("Dual-access sites", o["dual_access_sites"]["base"])
    st.caption("Only the backup count is decided by the seeded draw - the primary count "
               "follows from the footprint you supplied. That split is what the derived "
               "simulated share in step 6 is computed from.")
    st.caption(f"Model `{o['model_version']}` seed `{o['seed']}` ensemble {o['ensemble_size']}. "
               f"Re-running with the same seed and priors reproduces this hash exactly.")
    st.markdown("**Sample simulated edges** - note the diversity state.")
    st.dataframe(pd.DataFrame(o["sample_topology"]["edges"][:25]), use_container_width=True)

runs = api.get(f"/v1/outside-in/cases/{case_id}/simulations").get("runs", [])
if runs:
    st.divider(); st.subheader("Run history")
    st.caption("Simulation runs asynchronously. A cancelled run keeps its completed "
               "passes and resumes to the identical result, because every pass is a "
               "pure function of seed plus index.")
    st.dataframe(pd.DataFrame(runs), use_container_width=True)
