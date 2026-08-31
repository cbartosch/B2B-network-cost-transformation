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
_rows = [] if "_error" in _ev else _ev.get("footprint", [])
if _rows:
    st.success(f"Starting from {len(_rows)} promoted, evidenced row(s). "
               f"Edit freely - what you run is what is in the table below.")
    with st.expander("Where these came from"):
        st.dataframe(pd.DataFrame(_rows)[
            ["country", "archetype", "sites", "as_of", "promoted_by"]],
            use_container_width=True, hide_index=True)
    default = pd.DataFrame([{"country": r["country"],
                             "archetype": r["archetype"],
                             "sites": r["sites"]} for r in _rows])
else:
    # The case already declares which countries are in scope - the intake page
    # writes them, and Region/Global resolve to a literal list there. Opening
    # on four hardcoded demo rows meant the editor showed GB, DE, US, GB while
    # the case might be scoped to five other countries, and a country the
    # analyst never removed simply never appeared. Scope belongs to the case,
    # not to this page.
    _case = api.get(f"/v1/outside-in/cases/{case_id}")
    _countries = ([] if "_error" in _case
                  else list(_case.get("in_scope_countries") or []))
    if _countries:
        st.caption(
            f"No promoted research findings yet, so this opens on the "
            f"{len(_countries)} in-scope country(ies) from intake with one "
            f"site each - a placeholder, so the page is runnable, not an "
            f"estimate of anything. Replace them with real counts, add "
            f"archetype rows as needed, or research domain 2 and promote its "
            f"counts on page 5 to start from evidence. Whatever you type here "
            f"enters as ANALYST_ENTERED_SCOPE and is discounted accordingly.")
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


if st.button("Run simulation", type="primary"):
    footprint, problems = _clean_footprint(fp)
    for message in problems:
        st.error(message)
    if not problems and not footprint:
        st.error("No usable rows. Give at least one country, archetype and "
                 "site count.")
    elif not problems:
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
