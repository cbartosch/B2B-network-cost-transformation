import datetime as dt

import pandas as pd
import streamlit as st
import api_client as api

st.title("2. User- and publicly known facts register")
st.caption("Specification 0.1B - what the team already knows, captured as an "
           "attributable assumption. It never satisfies an evidence gate. "
           "Start from what is already public, then add what only you know.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

# The case already knows who the subject is. Leaving this blank cost a
# malformed fact - "(None sites)" with no subject, unresolvable forever - and
# it fragments the register: corroboration and the public-prefill dedupe both
# match on (fact_class, subject), so "HVB" and "UniCredit Bank GmbH" typed on
# different days become two facts about the same thing that never meet.
_case = api.get(f"/v1/outside-in/cases/{case_id}")
_entity = "" if "_error" in _case else (
    _case.get("subject_entity_legal_name") or "")
_aliases = [] if "_error" in _case else list(_case.get("entity_aliases") or [])
_countries = [] if "_error" in _case else list(_case.get("in_scope_countries") or [])

api.show_flash()


def _num(value):
    """A Decimal field arrives as a JSON string, so an editable numeric column
    has to be given a number rather than the string it came as."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


st.subheader("Start from what is already public")
st.caption("A quick sweep of public sources for the facts this register "
           "usually holds, run before the deep per-domain research. Nothing "
           "enters the register until you accept it in your own name. An "
           "accepted proposal arrives as THIRD_PARTY_REPORT with its sources "
           "attached, which is a stronger starting position than the same "
           "number typed from memory - an uncorroborated assertion caps "
           "confidence under 0.6A, a sourced one does not.")

if st.button("Look up public facts"):
    with st.spinner("Searching public sources..."):
        st.session_state["_prefill"] = api.post(
            f"/v1/outside-in/cases/{case_id}/known-facts:prefill-public", {},
            timeout=600.0)

_pf = st.session_state.get("_prefill")
if _pf and "_error" in _pf:
    st.error(_pf["_error"])
elif _pf:
    _props = _pf.get("proposals") or []
    if not _props:
        st.info("No public figures found for the swept fact classes. Your own "
                "knowledge is the only route for these - register them below.")
        if _pf.get("not_found"):
            st.caption("Nothing public found for: "
                       + ", ".join(_pf["not_found"]))
    else:
        st.write(f"{len(_props)} proposal(s) for **{_pf.get('subject')}**. "
                 f"Edit any cell before accepting: a searched figure is a "
                 f"starting point and the analyst is the one who decides what "
                 f"goes in the register.")

        # An editable table rather than a list of checkboxes. A proposal is
        # usually nearly right and wrong in one field - a stale as-of date, a
        # unit the source stated loosely, a value that needs rounding to the
        # perimeter - and a take-it-or-leave-it control forced a retype into
        # the form below to fix one cell.
        #
        # Editing does not launder the source: the sources stay attached to the
        # row, and `edited` is set on any row whose value the analyst changed,
        # so the register records that the figure is no longer exactly what the
        # source said.
        _rows = []
        for prop in _props:
            _srcs = prop.get("sources") or []
            _rows.append({
                "accept": not prop.get("already_registered"),
                "fact_class": prop.get("fact_class"),
                "subject": prop.get("subject"),
                "value_base": _num(prop.get("value_base")),
                "value_low": _num(prop.get("value_low")),
                "value_high": _num(prop.get("value_high")),
                "unit": prop.get("unit") or "",
                "currency": prop.get("currency") or "",
                "as_of": prop.get("as_of") or "",
                "sources": len(_srcs),
                "already_in_register": bool(prop.get("already_registered")),
                "_id": prop.get("proposal_id"),
            })
        _df = pd.DataFrame(_rows)
        _edited = st.data_editor(
            _df.drop(columns=["_id"]),
            use_container_width=True, hide_index=True, num_rows="fixed",
            disabled=["fact_class", "sources", "already_in_register"],
            column_config={
                "accept": st.column_config.CheckboxColumn(
                    "accept", help="Ticked rows are registered in your name."),
                "sources": st.column_config.NumberColumn(
                    "sources", help="How many public sources support this row. "
                                    "One is a thin finding, not a wrong one."),
                "already_in_register": st.column_config.CheckboxColumn(
                    "already registered",
                    help="Shown so you can see whether public sources agree "
                         "with what is already there."),
            }, key="pf_editor")

        with st.expander("Sources behind these proposals"):
            for prop in _props:
                st.markdown(f"**{prop['fact_class']} - {prop.get('subject')}**")
                for src in prop.get("sources") or []:
                    st.caption(
                        f"   {src.get('source_class') or ''} "
                        f"{src.get('publisher') or ''} {src.get('url') or ''}"
                        + (f" ({src['as_of']})" if src.get("as_of") else "")
                        + (f" [{src['how_read']}]" if src.get("how_read") else ""))
                if not prop.get("sources"):
                    st.caption("   no sources recorded on this proposal")

        who = st.text_input("Accepting as (your name)", key="pf_who")
        _picked = [
            {**_props[i], "value_base": r["value_base"],
             "value_low": r["value_low"], "value_high": r["value_high"],
             "unit": r["unit"] or None, "currency": r["currency"] or None,
             "as_of": r["as_of"] or None, "subject": r["subject"],
             # Recorded because an edited figure is no longer what the source
             # said, and the note is where that has to be visible.
             "edited": (r["value_base"] != _rows[i]["value_base"]
                        or r["subject"] != _rows[i]["subject"])}
            for i, r in enumerate(_edited.to_dict("records")) if r["accept"]]

        if st.button(f"Add {len(_picked)} row(s) to the register",
                     disabled=not (_picked and who.strip())):
            r = api.post(
                f"/v1/outside-in/cases/{case_id}/known-facts:accept-public",
                {"proposals": _picked, "accepted_by": who})
            if "_error" in r:
                st.error(r["_error"])
            else:
                api.flash(f"{len(r.get('registered') or [])} fact(s) "
                          f"registered as {who}. Edit any of them below.")
                for bad in r.get("refused") or []:
                    st.warning(f"{bad['fact_class']}: {bad['reason']}")
                st.session_state.pop("_prefill", None)
                st.rerun()

    if _pf.get("not_found"):
        st.caption("Nothing public found for: " + ", ".join(_pf["not_found"])
                   + ". That is a finding too - these need your knowledge or "
                     "the client's.")

st.divider()

# Downloadable, because the register is where hand-entered work accumulates and
# `docker compose down -v` drops the database volume - a command that appears in
# this project's own troubleshooting notes. Losing typed facts to a maintenance
# instruction is a failure of this system whichever layer removed the row.
_exp = api.get(f"/v1/outside-in/cases/{case_id}:export")
if "_error" not in _exp:
    import json as _json
    _counts = _exp.get("counts", {})
    st.download_button(
        f"Download this case ({_counts.get('known_facts', 0)} fact(s))",
        data=_json.dumps(_exp, indent=2, ensure_ascii=False),
        file_name=f"case_{case_id[:8]}.json", mime="application/json",
        help="The case, its known facts, its dispositions and any promoted "
             "footprint. Restore with tools/backup_cases.py, or POST it to "
             "/v1/outside-in/cases:import.")

st.caption(f"Register for **{_entity or 'this case'}** (case {case_id[:8]}). "
           f"Facts belong to one case; the active case is chosen on the home "
           f"page.")
_kf_list = api.get(f"/v1/outside-in/cases/{case_id}/known-facts")
if "_error" in _kf_list:
    # Silence here is the worst outcome: a register that failed to load looked
    # exactly like an empty one, so facts that were saved appeared to have been
    # lost, and re-entering them was the natural response. Same defect as the
    # footprint load on page 4, left in place here.
    facts = []
    st.error(f"**Could not load the register.** {_kf_list['_error']}")
    st.warning("This is a load failure, not an empty register. Nothing has "
               "been lost - do not re-enter facts until this is resolved, or "
               "you will end up with duplicates under slightly different "
               "subjects, which never corroborate each other.")
else:
    facts = _kf_list.get("known_facts", [])

if "_error" not in _kf_list and not facts:
    st.info(f"No known facts registered on this case "
            f"({case_id[:8]}). This is fine - the V0 will run without them. "
            f"Note that facts belong to one case: anything registered on a "
            f"different case does not appear here.")
elif facts:
    for f in facts:
        state = f["corroboration_state"]
        icon = {"CORROBORATED": "[+]", "CONTRADICTED": "[!]",
                "UNCORROBORATED": "[-]"}.get(state, "[ ]")
        _malformed = not (f.get("subject") or "").strip() or f.get("value_base") is None
        _label = (f"{icon} {f['fact_class']} - "
                  f"{f['subject'] or 'NO SUBJECT'} "
                  f"({'NO VALUE' if f['value_base'] is None else f['value_base']} "
                  f"{f['unit'] or ''}) - "
                  f"{'MALFORMED - cannot be corroborated' if _malformed else state}")
        with st.expander(_label):
            if _malformed:
                st.error(
                    "This fact carries no subject or no value, so there is no "
                    "claim to check against public sources - corroboration "
                    "will keep returning UNCORROBORATED however many times it "
                    "is run. It predates the validation that now refuses such "
                    "a fact at registration. Remove it and register it again "
                    "with a subject and a value.")
                if st.button("Remove this malformed fact",
                             key=f"rm_{f['known_fact_id']}"):
                    rr = api.post(
                        f"/v1/outside-in/known-facts/{f['known_fact_id']}:void",
                        {"voided_by": "analyst"})
                    if "_error" in rr:
                        st.error(rr["_error"])
                    else:
                        st.rerun()
            st.write({"asserted_by": f["asserted_by"], "assertion_date": f["assertion_date"],
                      "basis": f["basis"], "verifiability": f["verifiability"],
                      "rights_cleared": f["rights_cleared"],
                      "self_reported_confidence": f["self_reported_confidence"]})
            if f.get("corroboration_note"):
                st.caption(f["corroboration_note"])
            if f.get("provenance"):
                chain = api.get(f["provenance"])
                if "_error" not in chain:
                    rec = chain.get("provider_record") or {}
                    st.markdown("**Corroborating evidence**")
                    st.write({
                        "agent run": chain.get("corroborated_by_agent_run"),
                        "provider": rec.get("provider"),
                        "provider_request_id": rec.get("provider_request_id"),
                        "provider_response_id": rec.get("provider_response_id"),
                        "at": rec.get("provider_request_at"),
                        "provenance_strength": rec.get("provenance_strength")})
                    st.caption(chain.get("note") or "")
                    if not chain.get("verifiable_with_provider"):
                        st.warning("This corroboration carries no provider request "
                                   "identifier, so it cannot be spot-checked.")
            cols = st.columns(2)
            if not f["rights_cleared"]:
                who = cols[0].text_input("Rights cleared by", key=f"rc_{f['known_fact_id']}")
                if cols[0].button("Clear rights", key=f"rb_{f['known_fact_id']}", disabled=not who):
                    api.post(f"/v1/outside-in/known-facts/{f['known_fact_id']}:clear-rights",
                             {"cleared_by": who})
                    st.rerun()
            if f["verifiability"] == "PUBLICLY_VERIFIABLE" and state == "PENDING":
                if cols[1].button("Corroborate (LIVE)", key=f"co_{f['known_fact_id']}"):
                    with st.spinner("Calling provider..."):
                        r = api.post(
                            f"/v1/outside-in/known-facts/{f['known_fact_id']}:corroborate",
                            {"provider": "anthropic", "mode": "LIVE"})
                    if "_error" in r:
                        st.error(f"Run failed closed: {r['_error']}")
                    else:
                        st.session_state[f"obs_{f['known_fact_id']}"] = r
                        api.flash(f"{r['corroboration_state']}")
                        st.rerun()

            # Whatever the verdict, show what the sources said. A result that
            # reports only a state throws away the figures the search found,
            # which are usually the answer to the question actually being
            # asked - here, six sources giving branch counts against an
            # assertion made in sites.
            _res = st.session_state.get(f"obs_{f['known_fact_id']}")
            if isinstance(_res, dict):
                _obs = _res.get("observed") or {}
                _rows = (_obs.get("comparable") or []) + (_obs.get("other_unit") or [])
                if _rows:
                    st.markdown("**What public sources said**")
                    st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                                 hide_index=True)
                if _obs.get("other_unit") and not _obs.get("comparable"):
                    st.info("These are in a different unit from the assertion, "
                            "so they neither confirm nor contradict it. If the "
                            "asserted total is meant to be these plus other "
                            "site types, research domain 2 and promote the "
                            "per-type counts - a sum is a derivation and "
                            "belongs where its inputs are recorded, not in a "
                            "comparison that would then report a number no "
                            "source stated.")
                for _u in _res.get("unresolved_reasons") or []:
                    st.caption(f"- {_u}")
    st.caption("A corroborated fact is superseded by the public fact that corroborated it "
               "and stops counting toward asserted share (0.6A).")
