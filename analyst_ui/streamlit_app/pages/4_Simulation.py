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
_ev = api.get(f"/v1/outside-in/cases/{case_id}/evidenced-footprint")
_ev_failed = "_error" in _ev
_rows = [] if _ev_failed else _ev.get("footprint", [])

st.markdown("**Known sites by type**")
if _ev_failed:
    # Silence here reads as "nothing has been promoted", which is a different
    # situation with a different remedy. A promoted footprint that fails to
    # load looked identical to one that was never promoted, and the editor
    # quietly fell back to placeholders - so researched counts appeared to
    # vanish.
    st.error(f"**Could not load the promoted site list.** {_ev['_error']}")
    st.warning("The editor below has fallen back to placeholder values. Do "
               "not run on them believing they are the researched counts - "
               "fix the error above first, or the estimate will be built on "
               "defaults that look like findings.")
elif _rows:
    _total = sum(int(r.get("sites") or 0) for r in _rows)
    st.success(f"{_total:,} site(s) across {len({r['country'] for r in _rows})} "
               f"country(ies), promoted from research. Each row below shows "
               f"what it rests on.")
    st.dataframe(pd.DataFrame([{
        "country": r["country"],
        "type": r["archetype"],
        "sites": r["sites"],
        "sources said": (f"{r['band_low']}-{r['band_high']}"
                         if r.get("band_low") is not None
                         and r.get("band_high") is not None
                         and r["band_low"] != r["band_high"] else ""),
        "sources": r.get("source_count") or "",
        "as of": r.get("as_of") or "",
        "promoted by": r.get("promoted_by") or "",
    } for r in _rows]), use_container_width=True, hide_index=True)

    _by_type = {}
    for r in _rows:
        _by_type[r["archetype"]] = _by_type.get(r["archetype"], 0) + int(r.get("sites") or 0)
    st.caption("By type: " + ", ".join(f"{k} {v:,}" for k, v in sorted(_by_type.items()))
               + ". A row with one source is a single claim, not a corroborated "
                 "count - the sources column is worth reading before the number is.")

    with st.expander("Sources behind these counts"):
        for r in _rows:
            st.markdown(f"**{r['country']} {r['archetype']}: {r['sites']}**"
                        + (f"  (domain {r['domain_no']})" if r.get("domain_no") else ""))
            for url in r.get("source_urls") or []:
                st.caption(f"   {url}")
            if not r.get("source_urls"):
                st.caption("   no source URLs recorded on this row")
else:
    _who = ""
    try:
        _c = api.get(f"/v1/outside-in/cases/{case_id}")
        if "_error" not in _c:
            _who = (f" for **{_c.get('subject_entity_legal_name') or 'this case'}** "
                    f"(case {case_id[:8]})")
    except Exception:                                     # noqa: BLE001
        pass
    st.info(
        f"**No site list{_who} yet.** A promoted footprint belongs to one "
        f"case, so counts promoted on a different case do not appear here. "
        "The simulation does not look "
        "sites up - it takes the counts it is given and generates a circuit "
        "topology from them, so the number has to come from somewhere first. "
        "There are three routes, in descending order of what they are worth:\n\n"
        "1. **Research domain 2** on page 5, then promote the counts. They "
        "arrive here with their sources, their band and their as-of date, and "
        "the estimate treats them as public evidence.\n"
        "2. **Register what you know** on page 2 as a known fact, and "
        "corroborate it. An uncorroborated assertion caps confidence at 0.50 "
        "under 0.6A; a corroborated one does not.\n"
        "3. **Type them below.** They enter as ANALYST_ENTERED_SCOPE and are "
        "discounted accordingly - fine for a first pass, and visible as such "
        "in the confidence breakdown.")

st.caption("Whatever is in the table below is what runs. Edit freely.")

# The editor opens on the strongest thing available: promoted evidence, then
# the case's own in-scope countries at one site each, then illustrative rows
# only when the case has no scope at all.
# What was last run, so a typed footprint survives the rerun that follows
# running it. The editor was transient: counts entered by hand vanished the
# moment the simulation started, which read as the page collapsing to
# defaults. Ranked below promoted evidence and above any placeholder, because
# what you last ran is a better starting point than a guess and a worse one
# than a researched count.
_case_now = api.get(f"/v1/outside-in/cases/{case_id}")
_saved = ([] if "_error" in _case_now
          else list(_case_now.get("analyst_footprint") or []))

_last = []
_hist = api.get(f"/v1/outside-in/cases/{case_id}/simulations")
if "_error" not in _hist:
    for run in _hist.get("runs", []):
        _fp = (run.get("params") or {}).get("footprint") or []
        if _fp:
            _last = _fp
            break

if _rows:
    default = pd.DataFrame([{"country": r["country"],
                             "archetype": r["archetype"],
                             "sites": r["sites"]} for r in _rows])
elif _saved:
    st.caption(f"Opening on the {len(_saved)} saved row(s) for this case. "
               f"Analyst-entered, not researched - promote counts from page 5 "
               f"to replace them with evidence.")
    default = pd.DataFrame([{"country": r.get("country"),
                             "archetype": r.get("archetype"),
                             "sites": r.get("sites")} for r in _saved])
elif _last:
    st.caption(f"Opening on the {len(_last)} row(s) from your last run. These "
               f"are analyst-entered, not researched - promote counts from "
               f"page 5 to replace them with evidence.")
    default = pd.DataFrame([{"country": r.get("country"),
                             "archetype": r.get("archetype"),
                             "sites": r.get("sites")} for r in _last])
else:
    _case = api.get(f"/v1/outside-in/cases/{case_id}")
    _countries = ([] if "_error" in _case
                  else list(_case.get("in_scope_countries") or []))
    if _countries:
        # One, not zero. Zero was the honest default and made the page
        # unusable: the site-count guard refuses an all-zero footprint, so
        # nothing could be run without typing first. One is small enough that
        # nobody mistakes it for a finding - which was the actual concern -
        # while leaving the simulation reachable.
        default = pd.DataFrame([{"country": c, "archetype": "BRANCH", "sites": 1}
                                for c in _countries])
    else:
        st.caption("This case has no in-scope countries set, so this opens on "
                   "illustrative values. Set the scope on page 1.")
        default = pd.DataFrame([
            {"country": "GB", "archetype": "BRANCH", "sites": 120},
            {"country": "DE", "archetype": "BRANCH", "sites": 80},
            {"country": "US", "archetype": "LARGE_OFFICE", "sites": 12},
            {"country": "GB", "archetype": "DC", "sites": 2},
        ])
# --- what the register already says about site counts -----------------------
# A known fact of class "Location footprint" binds the sites driver at
# estimate time (page 6), and this page never read the register at all - so a
# registered count of 341 sat there while the editor showed a placeholder and
# the analyst was told to type it again. The register gives a total, not a
# breakdown by country and type, so the split is asked for rather than
# invented: the fact says how many sites there are, not what kind.
_kf = api.get(f"/v1/outside-in/cases/{case_id}/known-facts")
_site_facts = [] if "_error" in _kf else [
    f for f in _kf.get("facts", [])
    if f.get("fact_class") == "Location footprint"
    and f.get("value_base") is not None]

def _num(value):
    """Decimal fields arrive as JSON strings, so formatting one with :g raises
    rather than rendering. Coerced once, here, instead of at four call sites."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if _site_facts and not _rows:
    st.markdown("**From the known-facts register**")
    if len(_site_facts) > 1:
        _vals = [_num(f.get("value_base")) for f in _site_facts]
        _vals = [v for v in _vals if v]
        if _vals and max(_vals) / min(_vals) > 1.25:
            st.warning(
                f"**{len(_site_facts)} registered site counts disagree** "
                f"({min(_vals):g} to {max(_vals):g}). Where they are filed "
                f"under different names for the same company they are two "
                f"facts about one thing, and neither will ever corroborate "
                f"the other - the register matches on subject. Consolidate "
                f"them under one subject on page 2, or pick the one you mean "
                f"and say why in its note.")
    _options = {}
    for f in _site_facts:
        _v = _num(f.get("value_base"))
        if _v is None:
            continue
        _lo, _hi = _num(f.get("value_low")), _num(f.get("value_high"))
        _band = f"  (registered range {_lo:g}-{_hi:g})" if _lo and _hi else ""
        st.info(f"**{_v:g} {f.get('unit') or 'sites'}** - "
                f"{f.get('subject') or 'no subject'}{_band}. "
                f"{f.get('corroboration_state') or 'PENDING'}, asserted by "
                f"{f.get('asserted_by') or 'unattributed'}.")
        _options[f"{_v:g} {f.get('unit') or 'sites'} - "
                 f"{f.get('subject') or ''}"] = (f, _v)

    if _options:
        _use = st.selectbox("Use a registered count as the footprint",
                            ["-"] + list(_options))
        if _use != "-":
            _fact, _value = _options[_use]
            fc1, fc2 = st.columns(2)
            _country = fc1.selectbox(
                "Country these sites are in",
                (_case_now.get("in_scope_countries") or ["DE"])
                if "_error" not in _case_now else ["DE"])
            _arch = fc2.selectbox(
                "Site type",
                ["STORE", "BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC"],
                help="The register records how many sites there are, not what "
                     "kind. A bank branch is a customer-facing outlet - STORE "
                     "- which is priced differently from BRANCH, so this is "
                     "asked rather than guessed.")
            if st.button("Use this count"):
                _r = api.put(f"/v1/outside-in/cases/{case_id}", {
                    "analyst_footprint": [{"country": _country,
                                           "archetype": _arch,
                                           "sites": int(_value)}]})
                if "_error" in _r:
                    st.error(_r["_error"])
                else:
                    st.success(
                        f"Footprint set to {int(_value)} {_arch} sites in "
                        f"{_country}. Name this fact as the footprint source "
                        f"on page 6 so the estimate credits it - an "
                        f"uncorroborated assertion still caps confidence, a "
                        f"corroborated one lifts it.")
                    st.rerun()
    st.divider()

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
        for r in (_saved or [])]:
    st.warning("**Unsaved changes.** Streamlit discards an edited table when "
               "you switch page, so save or run before leaving - otherwise "
               "these figures are gone and the page reopens on the last saved "
               "set.")

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
