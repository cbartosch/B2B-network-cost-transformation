import time

import hashlib

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

# The choice sits outside the resolver's branches on purpose.
#
# It was nested inside `if _fp.get("register_total") is not None:`, which only
# one of six branches sets - so on a case with a saved footprint the panel
# silently did not render, and the analyst could not choose the total that
# would have fixed the disagreement they were looking at.
#
# Whether there is a choice to make is answered by the candidates call, not by
# which path the resolver happened to take.
_tc = api.get(f"/v1/outside-in/cases/{case_id}/footprint:total-candidates")
if "_error" in _tc:
    # A failing call rendered as nothing at all, which is indistinguishable
    # from "there is no choice to make" - and the most likely cause is a
    # migration that has not run, which the analyst can act on.
    st.error(f"Could not read the registered totals: {_tc['_error']}")
elif not (_tc.get("choices") or []):
    st.caption(
        "No registered site total on this case yet. Register one on page 2, "
        "or accept a Location footprint proposal from the public sweep - the "
        "footprint below is then reconciled against it.")
elif len(_tc["choices"]) == 1:
    _only = _tc["choices"][0]
    st.caption(
        f"One registered total: **{_only['sites']:,} "
        f"{_only['unit'] or 'sites'}** for {_only.get('subject')}, so there is "
        f"nothing to choose between. Register another on page 2 if the estate "
        f"spans scopes this one does not cover."
        + (f" Not offered: {len(_tc.get('rejected') or [])} fact(s) filed as "
           f"Location footprint that cannot be a count of sites."
           if _tc.get("rejected") else ""))
elif len(_tc.get("choices") or []) > 1:
    st.markdown("**Which total describes the estate you are modelling?**")
    st.caption(_tc.get("note", ""))

    def _total_label(choice):
        bits = [f"{choice['sites']:,} {choice['unit'] or 'sites'}"]
        if choice.get("corroboration_state"):
            bits.append(str(choice["corroboration_state"]))
        if choice.get("asserted_by"):
            bits.append(f"by {choice['asserted_by']}")
        return " - ".join(bits)

    _ids = [c["known_fact_id"] for c in _tc["choices"]]
    _current = _tc.get("chosen") or _tc.get("suggested")
    _pick_total = st.radio(
        "Registered totals", _ids,
        index=_ids.index(_current) if _current in _ids else 0,
        format_func=lambda i: _total_label(
            next(c for c in _tc["choices"] if c["known_fact_id"] == i)),
        key="sim_total_pick")
    _chosen_obj = next(c for c in _tc["choices"]
                       if c["known_fact_id"] == _pick_total)
    if _chosen_obj.get("supplied_note"):
        st.info(_chosen_obj["supplied_note"])
    if _chosen_obj.get("band"):
        st.caption(f"Source range: {_chosen_obj['band'].get('low')} to "
                   f"{_chosen_obj['band'].get('high')}.")
    if _tc.get("chosen"):
        st.caption(f"Currently modelling {_tc['chosen'][:8]}, chosen by "
                   f"{_tc.get('chosen_by')}.")
    _total_by = st.text_input("Choosing as (your name)", key="sim_total_by")
    if st.button("Use this total", disabled=not _total_by.strip()):
        _r = api.put(
            f"/v1/outside-in/cases/{case_id}/footprint:total-choice",
            {"known_fact_id": _pick_total, "chosen_by": _total_by})
        if "_error" in _r:
            st.error(_r["_error"])
        else:
            api.flash(_r.get("note", "Total chosen."))
            st.rerun()
elif "_error" not in _tc and _tc.get("rejected"):
    # Nothing to choose between, but something was rejected - the analyst
    # needs to know a fact exists and was not usable.
    for _rj in _tc["rejected"]:
        st.caption(f"Not offered as a site total: {_rj.get('value_base')} "
                   f"{_rj.get('unit') or ''} - {_rj['reason'][:140]}")

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
        # Which fact, and what else was in the running. "the register says
        # 3,912" is unanswerable without this: the resolver picks one fact from
        # several by standing then value, so a reader could not see which won.
        _tf = _fp.get("total_from") or {}
        if _tf:
            st.caption(
                f"That total comes from one fact: **{_tf.get('value_base')} "
                f"{_tf.get('unit') or 'sites'}** for {_tf.get('subject')}, "
                f"asserted by {_tf.get('asserted_by')} "
                f"({_tf.get('corroboration_state')}).")
        _others = _fp.get("other_footprint_facts") or []
        if _others:
            with st.expander(
                    f"{len(_others)} other Location footprint fact(s) not used"):
                st.dataframe(pd.DataFrame(_others),
                             use_container_width=True, hide_index=True)
                st.caption(
                    "The resolver takes one fact - best corroboration "
                    "standing, then largest value. That is right for competing "
                    "claims about the same thing and wrong for complementary "
                    "ones: 1,840 UK stores and 89 Ireland stores are both true "
                    "and the total is 1,929, not 1,840. If these are different "
                    "countries rather than rival estimates, register one "
                    "combined fact or allocate them by hand below.")
        st.caption(
            f"Registered total: {_fp['register_total']:,} sites. This "
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
    # A proposed split, rather than an empty table and an instruction to
    # invent one. It states its basis and is not applied until the analyst
    # saves or runs.
    if st.button("Propose a split for this total"):
        st.session_state["_split"] = api.get(
            f"/v1/outside-in/cases/{case_id}/footprint:propose-split")
    _sp = st.session_state.get("_split")
    if _sp and "_error" in _sp:
        st.error(_sp["_error"])
    elif _sp and _sp.get("rows"):
        st.info(_sp.get("note", ""))
        st.dataframe(pd.DataFrame(_sp["rows"]), use_container_width=True,
                     hide_index=True)
        if st.button("Put this in the table below", type="primary"):
            st.session_state["_split_apply"] = _sp["rows"]
            st.session_state.pop("_split", None)
            st.rerun()

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
        _la1, _la2, _la3 = st.columns(3)
        _laddr = _la1.text_input("Address", key="sim_loc_addr")
        _llat = _la2.text_input("Latitude", key="sim_loc_lat",
                                placeholder="48.137")
        _llon = _la3.text_input("Longitude", key="sim_loc_lon",
                                placeholder="11.575")
        _l6, _l7 = st.columns(2)
        _lasof = _l6.text_input("As of", key="sim_loc_asof",
                                placeholder="2025 or 2025-06-30")
        _lby = _l7.text_input("Entered by *", key="sim_loc_by")
        if st.button("Add this site",
                     disabled=not (_lc.strip() and _lby.strip())):
            _r = api.post(f"/v1/outside-in/cases/{case_id}/locations", {
                "country": _lc.upper(), "archetype": _lart,
                "city": _lcity or None, "name": _lname or None,
                "address": _laddr or None,
                "latitude": _llat or None, "longitude": _llon or None,
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
ARCHETYPES = ("BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC", "STORE")
DENSITY_BANDS = ["", "DENSE_URBAN", "URBAN", "SUBURBAN", "RURAL"]
# ------------------------------------------------- the working footprint
# What the analyst has in front of them, held in session until they save it,
# replace it, or the case changes. Nothing here reverts on its own.
#
# This was read fresh from the resolver every run, with an accepted proposal
# popped from session on the render that showed it - so by the time the analyst
# pressed Run the proposal was gone, the resolver's empty result came back, and
# the editor re-initialised to nothing. Run then reported "no usable rows" and
# Save wrote that emptiness over the case.
_fp_case = case_id
if st.session_state.get("_fp_case") != _fp_case:
    # A different case: start from what that case resolves to, not from what
    # the last one had in the table.
    st.session_state["_fp_case"] = _fp_case
    st.session_state["_fp_rows"] = None
    st.session_state["_fp_gen"] = 0

_applied = st.session_state.pop("_split_apply", None)
if _applied:
    st.session_state["_fp_rows"] = _applied
    st.session_state["_fp_gen"] = st.session_state.get("_fp_gen", 0) + 1

if st.session_state.get("_fp_rows") is None:
    # First visit to this case, or just after a save: take what the case
    # resolves to.
    st.session_state["_fp_rows"] = list(_resolved)

_working = st.session_state["_fp_rows"]
if _applied:
    st.success(f"{len(_applied)} proposed row(s) put in the table. Correct "
               f"them, then Save or Run - nothing is stored until you do.")

default = pd.DataFrame(
    [{"country": r.get("country"), "archetype": r.get("archetype"),
      "density": r.get("density") or "", "sites": r.get("sites")}
     for r in _working]
    or [{"country": "", "archetype": "", "density": "", "sites": 0}])

# The key changes only when the data is deliberately replaced - a proposal, a
# promotion, a different case - and never because a cell was edited.
#
# Hashing the content was the wrong fix: it made the key follow `default`, and
# `default` reverted every run, so the editor discarded the edits it was meant
# to protect. A generation counter separates "the analyst changed a cell", which
# must persist, from "the source rows changed", which must refresh.
_fp_key = f"sim_fp_{case_id[:8]}_{st.session_state.get('_fp_gen', 0)}"
fp = st.data_editor(
    default, num_rows="dynamic", use_container_width=True, key=_fp_key,
    column_config={
        "density": st.column_config.SelectboxColumn(
            "density", options=DENSITY_BANDS,
            help="Where these sites are. Leave blank and the row prices as it "
                 "always did. Set it and what can actually be delivered there "
                 "is resolved against what this site type asks for - which is "
                 "the difference between a rural discounter and an urban one."),
        "archetype": st.column_config.SelectboxColumn(
            "archetype", options=[""] + list(ARCHETYPES)),
    })

# Written back, so what is on screen survives the next rerun whatever caused
# it. A button press is a rerun, and the table has to still be there when the
# handler reads it.
st.session_state["_fp_rows"] = [
    {"country": r.get("country"), "archetype": r.get("archetype"),
     "density": r.get("density") or None, "sites": r.get("sites")}
    for r in fp.to_dict("records")]

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
        # Density is optional and validated when present: a misspelled band
        # would silently make the row unclustered, which prices as though
        # nothing was known about where the sites are.
        density = _text(raw.get("density"))
        if density and density not in DENSITY_BANDS:
            problems.append(
                f"row {i}: density {density!r} is not one of "
                f"{', '.join(b for b in DENSITY_BANDS if b)}")
            continue
        rows.append({"country": country, "archetype": archetype,
                     "sites": sites, "density": density or None})
    return rows, problems



_edited, _edit_problems = _clean_footprint(fp)

# Read from the resolver rather than restated here. A literal copy of a
# governed threshold means a steward who retunes it gets an interface that
# disagrees with the API about what will be accepted.
# The limit follows how much the row says. A row with a density band is a real
# cluster - same country, same type, same deliverable access - and claims far
# less than one asserting a whole country's estate is alike.
_ROW_LIMIT = (_fp or {}).get("max_sites_per_archetype_row") or 100
_CLUSTER_LIMIT = (_fp or {}).get("max_sites_per_cluster_row") or 2000
_coarse = [r for r in _edited
           if r["sites"] > (_CLUSTER_LIMIT if r.get("density") else _ROW_LIMIT)]
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
            # Cleared so the next run re-reads what was actually stored. Left
            # in place, the working copy would go stale in the other direction
            # and the table would show what was typed rather than what the case
            # now holds.
            st.session_state["_fp_rows"] = None
            st.session_state["_fp_gen"] = st.session_state.get("_fp_gen", 0) + 1
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

    # What the density bands said about the estate. A uniform estate is an
    # assumption, and this is the first thing that tests it.
    _svc = o.get("serviceability") or {}
    _unserv = o.get("unserviceable") or []
    if _svc.get("counts"):
        _c = _svc["counts"]
        st.markdown("**What can actually be delivered**")
        (st.success if not _c.get("SUBSTITUTED") and not _unserv
         else st.warning)(_svc.get("note", ""))
        if _svc.get("table_basis") == "ABSENT":
            st.error(
                "**This run had no serviceability data to judge against.** "
                "reference.serviceability is empty or was not pinned to the "
                "run, so nothing could be confirmed deliverable. Re-seed with "
                "`python -m app.seed --force` and run again - and treat any "
                "'cannot be served' above as an artefact, not a finding.")
        else:
            st.caption(f"Judged against {_svc.get('table_rows', 0)} governed "
                       f"serviceability row(s).")
        if _svc.get("substitutions"):
            st.dataframe(pd.DataFrame(_svc["substitutions"]),
                         use_container_width=True, hide_index=True)
        for _u in _unserv:
            st.error(
                f"**{_u['sites']:,} site(s) in {_u['density']} {_u['country']} "
                f"cannot be served at all.** {_u['reason']} They are not in the "
                f"estate and not priced - decide whether the density band is "
                f"wrong, or whether these sites need a different site type.")

    # The estate the estimate is built on, site by site. Every circuit priced
    # downstream belongs to a row here, and every row says whether the site is
    # one somebody named or one the pass generated to make the count up.
    _estate = o.get("estate") or []
    if _estate:
        _named = o.get("sites_named", 0)
        _gen = o.get("sites_generated", 0)
        st.markdown("**The estate, site by site**")
        (st.success if _named and not _gen else st.info)(
            f"{_named + _gen:,} site(s): **{_named:,} named**, "
            f"{_gen:,} generated to make the count up. A generated row carries "
            f"no name, address or position - there is nowhere on it to put "
            f"one, so it cannot be read as a site anybody knows.")
        if o.get("estate_truncated"):
            st.caption(f"Showing the first {len(_estate):,}; "
                       f"{o['estate_truncated']:,} more were not stored. "
                       f"A JSON column is not a site register.")
        _only_named = st.checkbox("Named sites only", key="sim_estate_named")
        _show = [r for r in _estate if r.get("known")] if _only_named else _estate
        st.dataframe(pd.DataFrame([{
            "site": r.get("site_id"), "known": r.get("known"),
            "country": r.get("country"), "type": r.get("archetype"),
            "name": r.get("name") or "", "city": r.get("city") or "",
            "address": r.get("address") or "",
            "lat": r.get("latitude"), "lon": r.get("longitude"),
            "users": r.get("users"), "Mbps": r.get("bandwidth_mbps"),
            "primary": r.get("primary_product"),
            "backup": r.get("backup_product") or "",
            "grade": r.get("reliability_grade") or "",
        } for r in _show[:1000]]), use_container_width=True, hide_index=True)
        import json as _json
        st.download_button(
            "Download the estate as JSON",
            data=_json.dumps(_estate, indent=2, default=str),
            file_name=f"estate_{case_id[:8]}.json", mime="application/json",
            help="The list every priced circuit belongs to. A generated row is "
                 "marked known=false and carries no identity.")

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
