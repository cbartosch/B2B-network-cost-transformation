import time

import pandas as pd
import streamlit as st
import api_client as api

st.title("5. Topology and architecture simulation")
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


api.show_flash()
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
_case_settings = api.get(f"/v1/outside-in/cases/{case_id}")

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
        "KNOWN_FACT_UNALLOCATED": ("Registered, not yet allocated", st.warning),
        "KNOWN_FACT_SPLIT": ("Register total, your breakdown", st.info),
        "ANALYST_SAVED": ("Saved on this case", st.info),
        "SCOPE_PLACEHOLDER": ("Placeholder", st.warning),
        "ILLUSTRATIVE": ("Illustrative", st.warning),
    }
    _title, _render = _labels.get(_origin, (_origin, st.info))
    _total = sum(int(r.get("sites") or 0) for r in _resolved)
    _render(f"**{_title}** - {_total:,} site(s) across "
            f"{len({r.get('country') for r in _resolved})} country(ies). "
            f"{_detail}")

    if _fp.get("diverges"):
        st.error(_fp.get("split_note", ""))
    elif _fp.get("needs_split"):
        st.warning(_fp.get("split_note", ""))
    if _fp.get("register_total") is not None:
        st.caption(f"Registered total: {_fp['register_total']:,} sites. This "
                   f"page never changes it - the register is altered only on "
                   f"page 2.")

    # Why the stronger sources were not used. Five rounds went on "the
    # footprint is wrong" because the answer was not observable from the page.
    _considered = _fp.get("considered") or []
    _skipped = [c for c in _considered if not c.get("used")]
    if _skipped:
        with st.expander(f"Why not the other {len(_skipped)} source(s)?",
                         expanded=_origin in ("SCOPE_PLACEHOLDER",
                                              "ILLUSTRATIVE")):
            for c in _considered:
                _mark = "used" if c.get("used") else "not used"
                st.markdown(f"**{c['source']}** - {_mark}")
                st.caption(f"   {c.get('reason') or ''}")

    if _resolved:
        st.dataframe(pd.DataFrame([{
            "country": r.get("country"), "type": r.get("archetype"),
            "sites": r.get("sites")} for r in _resolved]),
            use_container_width=True, hide_index=True)

    if _origin in ("ANALYST_SAVED", "KNOWN_FACT_SPLIT"):
        # Clearing a stale breakdown should not require finding an endpoint.
        if st.button("Clear the saved breakdown"):
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
            "page 4, or register what you know on page 2 - a registered "
            "Location footprint fact is picked up here automatically.")

_unallocated = (_fp or {}).get("unallocated_sites")
if _unallocated:
    st.info(
        f"**{_unallocated:,} registered sites to allocate.** Add a row per "
        f"country and site type below and the remainder is tracked as you go. "
        f"Nothing is guessed for you - a plausible mix is still a mix nobody "
        f"decided, and it would be priced as though someone had.")
    _sugg = (_fp or {}).get("suggested_country")
    if _sugg:
        st.caption(f"Suggested country for the first rows: {_sugg}. Site types: "
                   f"STORE for a customer-facing outlet (trade counter, bank "
                   f"branch, shop), WAREHOUSE for a depot, plant or "
                   f"distribution centre, LARGE_OFFICE for a headquarters or "
                   f"regional office, DC for a computing facility, BRANCH for a "
                   f"small non-customer-facing site.")

# --------------------------------------------------- the named locations
st.markdown("**Named locations**")
_loc = api.get(f"/v1/outside-in/cases/{case_id}/locations")
if "_error" in _loc:
    st.error(_loc["_error"])
else:
    _enum = _loc.get("enumeration") or {}
    _rows_loc = _loc.get("locations") or []
    _share = float(_enum.get("enumerated_share") or 0)

    # Stated plainly. An itemised list of what is known beats no list, and it
    # is only useful if the reader can see how much of the estate it covers -
    # a list of 47 sites out of 440 read as a footprint would be worse than
    # having no list at all.
    if _enum.get("total"):
        (st.success if _share >= 0.9 else st.info if _share > 0 else st.warning)(
            f"**{_enum.get('enumerated', 0)} of {_enum.get('total', 0)} site(s) "
            f"are named** ({_share:.0%}). The rest are a tally: real, counted, "
            f"and not individually known. The unnamed share is priced by "
            f"applying the named mix to it, which is an inference - so it "
            f"carries PUBLIC_DERIVED and lowers the origin mix accordingly.")

    if _enum.get("by_country"):
        st.dataframe(pd.DataFrame([{
            "country": c, "total": v["total"], "named": v["enumerated"],
            "named share": v["enumerated_share"], "tallied": v["residual"],
            "named mix": ", ".join(f"{k} {n}" for k, n in
                                   (v["enumerated_mix"] or {}).items()) or "-",
        } for c, v in (_enum.get("by_country") or {}).items()]),
            use_container_width=True, hide_index=True)

    for _c in _enum.get("conflicts") or []:
        st.error(_c["note"])
    for _d in _enum.get("duplicates") or []:
        _byid = {r["location_id"]: r for r in _rows_loc}
        _a, _b = _d["location_id"], _d["duplicate_of"]
        def _label(_i):
            _r = _byid.get(_i) or {}
            return (f"{_r.get('city') or ''} {_r.get('name') or ''}".strip()
                    or str(_i)[:8])
        st.warning(f"**Possible duplicate:** {_label(_a)} and {_label(_b)}. "
                   f"{_d['note']}")
        _dc1, _dc2 = st.columns(2)
        if _dc1.button(f"Same site - fold {_label(_a)} into {_label(_b)}",
                       key=f"dup_y_{_a}"):
            _r = api.post(
                f"/v1/outside-in/cases/{case_id}/locations/{_a}:duplicate-of"
                f"?of={_b}", {})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash("Marked as one site. It stops counting toward the "
                          "named share and is not deleted - reversible, because "
                          "the key that suspected it folds accents and drops "
                          "branch words.")
                st.rerun()
        if _dc2.button("Different sites - dismiss", key=f"dup_n_{_a}"):
            _r = api.post(
                f"/v1/outside-in/cases/{case_id}/locations/{_a}:duplicate-of"
                f"?of=", {})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash("Dismissed.")
                st.rerun()

    with st.expander(f"The {len(_rows_loc)} named site(s)",
                     expanded=bool(_rows_loc) and len(_rows_loc) <= 30):
        if _rows_loc:
            st.dataframe(pd.DataFrame([{
                "country": r.get("country"), "city": r.get("city"),
                "name": r.get("name"), "type": r.get("archetype"),
                "as of": r.get("as_of"), "source": r.get("publisher")
                or (r.get("source_url") or "")[:40],
                "grade": r.get("reliability_grade") or "",
                "by": r.get("entered_by"),
            } for r in _rows_loc]), use_container_width=True, hide_index=True)
            _rm = st.selectbox(
                "Remove a site (closed, or outside the perimeter)",
                ["-"] + [f"{r.get('country')} {r.get('city') or ''} "
                         f"{r.get('name') or ''} [{r['location_id'][:8]}]"
                         for r in _rows_loc], key="sim_loc_rm")
            if _rm != "-" and st.button("Remove it"):
                _id = _rm.rsplit("[", 1)[1].rstrip("]")
                _full = next((r["location_id"] for r in _rows_loc
                              if r["location_id"].startswith(_id)), None)
                _r = api.delete(
                    f"/v1/outside-in/cases/{case_id}/locations/{_full}")
                if "_error" in _r:
                    st.error(_r["_error"])
                else:
                    api.flash("Site removed. The footprint total is unchanged - "
                              "correct it on page 2 if the total is what is wrong.")
                    st.rerun()
        else:
            st.caption("None yet. Most companies publish enough to name some: "
                       "a store locator, a service-hub page, a branch list in "
                       "an annual report. Even a dozen makes the count "
                       "checkable and shows in the named share above.")

    with st.expander("Add a named site"):
        _l1, _l2, _l3 = st.columns(3)
        _lc = _l1.text_input("Country", max_chars=2, key="sim_loc_c")
        _lcity = _l2.text_input("City", key="sim_loc_city")
        # Read from the resolver's own list rather than the module constant
        # below, which is declared after this panel - referencing it here was a
        # NameError at render that compiles clean.
        _lart = _l3.selectbox(
            "Site type",
            ["BRANCH", "STORE", "WAREHOUSE", "LARGE_OFFICE", "DC"],
            key="sim_loc_a",
            help="The same five the footprint uses; the API refuses anything "
                 "not in reference.archetype_prior.")
        _l4, _l5 = st.columns(2)
        _lname = _l4.text_input("Name", key="sim_loc_n")
        _lsrc = _l5.text_input("Source URL or publisher", key="sim_loc_s")
        _l6, _l7 = st.columns(2)
        _lasof = _l6.text_input("As of", key="sim_loc_asof",
                                placeholder="2025 or 2025-06-30")
        _lby = _l7.text_input("Entered by *", key="sim_loc_by")
        if st.button("Add this site",
                     disabled=not (_lc.strip() and _lby.strip())):
            _r = api.post(f"/v1/outside-in/cases/{case_id}/locations", {
                "country": _lc.upper(), "archetype": _lart,
                "city": _lcity or None, "name": _lname or None,
                "source_url": _lsrc if (_lsrc or "").startswith("http") else None,
                "publisher": None if (_lsrc or "").startswith("http") else (_lsrc or None),
                "as_of": _lasof or None, "entered_by": _lby})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash("Site added. The footprint total is unchanged: a list "
                          "is evidence for the count, not a replacement of it.")
                st.rerun()

st.caption("Whatever is in the table below is what runs. Edit it, then Save or "
           "Run - both persist it to the case.")
default = pd.DataFrame(
    [{"country": r.get("country"), "archetype": r.get("archetype"),
      "sites": r.get("sites")} for r in _resolved]
    or [{"country": "", "archetype": "", "sites": 0}])

fp = st.data_editor(default, num_rows="dynamic", use_container_width=True, key="sim_fp")

c1, c2 = st.columns(2)
# Read from the case, not defaulted. A pinned seed is the whole basis of the
# reproducibility claim, and it was widget state - so switching page reverted
# it to 42 and the next run was a different ensemble with no notice.
_rs = ({} if "_error" in _case_settings else (_case_settings.get("run_settings") or {}))
seed = c1.number_input("Seed", 0, 10**9, int(_rs.get("seed") or 42),
                       help="The whole ensemble is reproducible from this one "
                            "integer. Saved with the footprint, so it survives "
                            "a page switch.", key="sim_seed")
size = c2.number_input("Ensemble size", 1, 200,
                       int(_rs.get("ensemble_size") or 25), key="sim_size")

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

# Read from the resolver rather than restated here. A literal copy of a
# governed threshold means a steward who retunes it gets an interface that
# disagrees with the API about what will be accepted.
_ROW_LIMIT = (_fp or {}).get("max_sites_per_archetype_row") or 100
_coarse = [r for r in _edited if r["sites"] > _ROW_LIMIT]
if _coarse:
    st.error(
        "**These rows carry too many sites to be one row:** "
        + "; ".join(f"{r['country']} {r['archetype']} {r['sites']:,}"
                    for r in _coarse)
        + f". A row asserts that every site in it is identical - one bandwidth, "
          f"one primary and backup product, one dual-access probability - and "
          f"the whole row is priced at that archetype's tier. Split them by "
          f"site type. The run is refused above {_ROW_LIMIT} per row.")

if _unallocated:
    _done = sum(r["sites"] for r in _edited)
    _left = _unallocated - _done
    if _left > 0:
        st.warning(f"{_done:,} of {_unallocated:,} allocated - "
                   f"**{_left:,} still to place.** The run uses what is in the "
                   f"table, so anything unallocated is simply not modelled.")
    elif _left < 0:
        st.error(f"{_done:,} allocated against a registered {_unallocated:,} - "
                 f"**{abs(_left):,} more than the register holds.** Correct the "
                 f"table, or change the fact on page 2 if the registered total "
                 f"is what is wrong.")
    else:
        st.success(f"All {_unallocated:,} registered sites allocated.")
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
                     {"analyst_footprint": _rows_to_save,
                      "run_settings": {**_rs, "seed": int(seed),
                                       "ensemble_size": int(size)}})
        if "_error" in _r:
            st.error(_r["_error"])
        else:
            api.flash(f"Saved {len(_rows_to_save)} row(s) to the case. "
                      f"They will be here next time without running anything.")
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
                {"analyst_footprint": footprint,
                 "run_settings": {**_rs, "seed": int(seed),
                                  "ensemble_size": int(size)}})
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
    _topo = (sim.get("pinned_priors") or {}).get("topology_basis") or {}
    if _topo:
        _ev, _as = _topo.get("evidenced_fields") or [], _topo.get("assumed_fields") or []
        st.markdown("**How each site type is built**")
        (st.success if _ev else st.warning)(
            f"{len(_ev)} of {len(_ev) + len(_as)} topology field(s) come from "
            f"this case's own evidence; {len(_as)} are still seeded "
            f"assumptions.")
        st.dataframe(pd.DataFrame([{
            "site type": k.split(".")[0], "dimension": k.split(".")[1],
            "value": v.get("value"),
            "from": {"SEEDED_PRIOR": "seeded default",
                     "INDUSTRY_DEFAULT": "industry default",
                     "KNOWN_FACT": "known-facts register",
                     "PROMOTED_RESEARCH": "promoted research"}.get(
                         v.get("layer"), v.get("layer")),
            "grade": v.get("grade") or "",
        } for k, v in (_topo.get("by_field") or {}).items()]),
            use_container_width=True, hide_index=True)
        st.caption(_topo.get("note", ""))

    _basis = (sim.get("pinned_priors") or {}).get("bandwidth_basis") or {}
    if _basis:
        st.markdown("**Bandwidth by site type**")
        st.caption(
            (f"Industry **{_basis.get('industry')}**."
             if _basis.get("matched") else
             "No industry set on this case, so the generic DEFAULT tiers are "
             "used. Set the industry on page 1 to price site types for the "
             "sector - a retail bank branch and a parts depot of the same size "
             "do not need the same circuit.")
            + " The archetype says what shape a site is; the industry says "
              "what happens inside it, and the bandwidth follows from both.")
        st.dataframe(pd.DataFrame(
            [{"site type": a, "bandwidth (Mbps)": b}
             for a, b in (_basis.get("by_archetype") or {}).items()]),
            use_container_width=True, hide_index=True)

    st.markdown("**Sample simulated edges** - note the diversity state and the "
                "bandwidth each circuit is priced at.")
    st.dataframe(pd.DataFrame(o["sample_topology"]["edges"][:25]),
                 use_container_width=True)

runs = api.get(f"/v1/outside-in/cases/{case_id}/simulations").get("runs", [])
if runs:
    st.divider(); st.subheader("Run history")
    st.caption("Simulation runs asynchronously. A cancelled run keeps its completed "
               "passes and resumes to the identical result, because every pass is a "
               "pure function of seed plus index.")
    st.dataframe(pd.DataFrame(runs), use_container_width=True)
