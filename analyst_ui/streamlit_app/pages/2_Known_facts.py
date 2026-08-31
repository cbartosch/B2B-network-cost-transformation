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
                "knowledge is the only route for these - register it below.")
    else:
        st.write(f"Found {len(_props)} proposal(s) for "
                 f"**{_pf.get('subject')}**.")
        chosen = []
        for prop in _props:
            band = ""
            if prop.get("value_low") is not None and prop.get("value_high") is not None:
                band = f"  (sources range {prop['value_low']}-{prop['value_high']})"
            label = (f"{prop['fact_class']} - {prop['subject']}: "
                     f"{prop.get('value_base') if prop.get('value_base') is not None else '?'} "
                     f"{prop.get('unit') or ''}{band}")
            cols = st.columns([6, 1])
            picked = cols[0].checkbox(label, key=f"pf_{prop['proposal_id']}",
                                      value=not prop.get("already_registered"))
            if prop.get("bindable"):
                cols[1].caption("binds a driver")
            if prop.get("already_registered"):
                st.caption("   Already in the register - shown so you can see "
                           "whether public sources agree with what is there.")
            if prop.get("note"):
                st.caption(f"   {prop['note']}")
            for src in prop.get("sources") or []:
                st.caption(f"   source: {src.get('publisher') or ''} "
                           f"{src.get('url') or ''}"
                           + (f" ({src['as_of']})" if src.get("as_of") else ""))
            if picked:
                chosen.append(prop)

        who = st.text_input("Accepting as (your name)", key="pf_who")
        if st.button("Add selected to the register",
                     disabled=not (chosen and who.strip())):
            r = api.post(
                f"/v1/outside-in/cases/{case_id}/known-facts:accept-public",
                {"proposals": chosen, "accepted_by": who})
            if "_error" in r:
                st.error(r["_error"])
            else:
                st.success(f"{len(r.get('registered') or [])} fact(s) "
                           f"registered as {who}.")
                for bad in r.get("refused") or []:
                    st.warning(f"{bad['fact_class']}: {bad['reason']}")
                st.session_state.pop("_prefill", None)
                st.rerun()

    if _pf.get("not_found"):
        st.caption("Nothing public found for: " + ", ".join(_pf["not_found"])
                   + ". That is a finding too - these need your knowledge or "
                     "the client's.")

st.divider()

# Deliberately not st.form. A form does not write its widget values to session
# state until it is submitted, so navigating to another page mid-entry discarded
# everything typed - which is what "the information I entered is gone" meant all
# along, and it was the register I kept fixing. Plain keyed widgets write to
# session state as they change, so a half-finished fact survives a page switch.
#
# The cost is a rerun per keystroke-group, which on this page is unnoticeable.
_KF_FIELDS = {
    "kf_fact_class": "Location footprint",
    "kf_subject": _entity,
    "kf_base": None, "kf_low": None, "kf_high": None,
    "kf_unit": "sites",
    "kf_asserted_by": "",
    "kf_basis": "CLIENT_CONVERSATION",
    "kf_verif": "PUBLICLY_VERIFIABLE",
    "kf_date": dt.date.today(),
    "kf_conf": 0.6,
}
for _k, _default in _KF_FIELDS.items():
    st.session_state.setdefault(_k, _default)

st.markdown("**Register a known fact**")
if any(st.session_state.get(k) not in (None, "", _KF_FIELDS[k])
       for k in ("kf_base", "kf_low", "kf_high", "kf_asserted_by")):
    st.caption("Draft in progress - it is kept if you move to another page and "
               "come back.")

_CLASSES = ["Location footprint", "Current architecture hypothesis",
            "Public cost evidence", "Current vendor and product signals",
            "Contract and sourcing events", "Operating-model cost",
            "Transformation announcements", "Resilience assumptions",
            "Remote-user population", "Market serviceability"]
_BASES = ["CLIENT_CONVERSATION", "INDUSTRY_KNOWLEDGE", "THIRD_PARTY_REPORT",
          "PRIOR_ENGAGEMENT", "UNSTATED"]
_VERIF = ["PUBLICLY_VERIFIABLE", "CLIENT_CONFIRMABLE", "UNVERIFIABLE"]

a, b = st.columns(2)
fact_class = a.selectbox("Fact class", _CLASSES, key="kf_fact_class")
_suggestions = [x for x in ([_entity] + _aliases + _countries) if x]
subject = b.text_input(
    "Subject *", key="kf_subject",
    help="The entity, country, provider or contract the claim is about, "
         "prefilled from the case. Change it where the claim is not about the "
         "entity itself - a country for market serviceability, a carrier for a "
         "contract event. Keep the wording consistent between facts about the "
         "same thing: corroboration and the public prefill both match on it.")
if _suggestions:
    b.caption("Also on this case: " + " · ".join(_suggestions[:5]))

c, d, e, f = st.columns(4)
# value=None rather than 0.0. The field defaulted to 0.0 and the payload then
# did `base or None`, so an untouched field silently became "no value" - and a
# legitimate zero became one too. The fact registered as "(None sites)" with an
# empty subject, and every stage downstream behaved correctly on something that
# should never have been storable.
base = c.number_input("Value (base) *", value=None, placeholder="e.g. 340",
                      key="kf_base")
low = d.number_input("Low (optional)", value=None, key="kf_low")
high = e.number_input("High (optional)", value=None, key="kf_high")
unit = f.text_input("Unit", key="kf_unit")

g, h, i = st.columns(3)
asserted_by = g.text_input("Asserted by *", key="kf_asserted_by",
                           help="A named individual. Not a team or a role.")
basis = h.selectbox("Basis", _BASES, key="kf_basis")
verif = i.selectbox("Verifiability", _VERIF, key="kf_verif")

j, k = st.columns(2)
adate = j.date_input("Assertion date", key="kf_date")
conf = k.slider("Self-reported confidence", 0.0, 1.0, key="kf_conf")

if basis == "PRIOR_ENGAGEMENT":
    st.warning("A PRIOR_ENGAGEMENT fact may carry another client's "
               "confidential information. It starts un-cleared and cannot "
               "influence the estimate until a rights check passes (2.4).")

_reg, _clear = st.columns([1, 4])
if _clear.button("Clear the form"):
    for _k, _default in _KF_FIELDS.items():
        st.session_state[_k] = _default
    st.rerun()

if _reg.button("Register", type="primary"):
    problems = []
    if not (asserted_by or "").strip():
        problems.append("An unattributed known fact is rejected. Name the asserter.")
    if not (subject or "").strip():
        problems.append("Name the subject. Corroboration looks for public "
                        "sources about a named subject.")
    if base is None and low is None and high is None:
        problems.append("Give a value - a point in base, or a range in low and "
                        "high. If the number is genuinely unknown, leave the "
                        "domain DECLARED_UNKNOWN rather than asserting an "
                        "empty fact.")
    if problems:
        for msg in problems:
            st.error(msg)
    else:
        r = api.post(f"/v1/outside-in/cases/{case_id}/known-facts", {
            "fact_class": fact_class, "subject": subject,
            # No `or None`: that coerced a legitimate zero to absent as well
            # as an untouched field.
            "value_base": base, "value_low": low, "value_high": high,
            "unit": unit,
            "asserted_by": asserted_by, "assertion_date": str(adate),
            "basis": basis, "verifiability": verif,
            "self_reported_confidence": conf})
        if "_error" in r:
            st.error(r["_error"])
        else:
            _msg = (f"Registered {fact_class} for {subject} as "
                    f"{r.get('evidence_origin')} "
                    f"(id {str(r.get('known_fact_id'))[:8]}).")
            if r.get("range_widened_from_point"):
                _msg += (" The point value was widened to a range; the "
                         "widening is recorded.")
            api.flash(_msg)
            # Cleared only on success, so a rejected attempt keeps what was
            # typed instead of making the analyst start again.
            for _k, _default in _KF_FIELDS.items():
                st.session_state[_k] = _default
            st.rerun()

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
