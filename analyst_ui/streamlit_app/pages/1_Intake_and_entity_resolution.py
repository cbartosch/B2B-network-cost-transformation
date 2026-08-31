import streamlit as st
import api_client as api

st.title("1. Intake and entity resolution")
st.caption("Specification 0.1A - no research, agent run, prior lookup or calculation "
           "may execute against a case until the subject entity is confirmed.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select or create a case on the home page first.")
    st.stop()

case = api.get(f"/v1/outside-in/cases/{case_id}")

st.subheader("Mandatory intake block")

is_locked = bool(case.get("resolved_entity_id"))
if is_locked:
    st.info("Entity confirmed - legal name, identifier, domicile and group "
           "perimeter are locked so an estimate's provenance can't drift from "
           "what was actually confirmed. To change any of them, resolve and "
           "confirm the entity again below; that's what advances the "
           "perimeter version.")

# Scope mode lives outside the form: a form batches its own widgets and only
# reruns the script on submit, so a radio inside it can't reveal or hide the
# field beside it before the analyst has already submitted once. Outside the
# form, picking a mode immediately swaps in the right input below.
_scope_modes = ["COUNTRIES", "REGION", "GLOBAL"]
_current_region = case.get("in_scope_region")
_default_mode = "GLOBAL" if _current_region == "GLOBAL" else \
    "REGION" if _current_region else "COUNTRIES"
scope_mode = st.radio(
    "In-scope geography *", _scope_modes, index=_scope_modes.index(_default_mode),
    format_func=lambda m: {"COUNTRIES": "Specific countries", "REGION": "Region",
                           "GLOBAL": "Global"}[m],
    horizontal=True,
    help="Region and Global resolve to a literal country list when you save - "
         "only countries with an approved pricing benchmark can be priced "
         "either way, so the resolved list is shown back to you after saving.")

region_options = api.get("/v1/outside-in/regions").get("regions", [])

with st.form("intake"):
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Subject entity legal name *", case.get("subject_entity_legal_name") or "",
                         help="Exact registered legal name - not a trading or brand name",
                         disabled=is_locked)
    ident = c2.text_input("Entity identifier *", case.get("entity_identifier") or "",
                          help="LEI, ticker plus exchange, registration number or primary domain",
                          disabled=is_locked)
    dom = c3.text_input("Country of domicile *", case.get("country_of_domicile") or "",
                        max_chars=2, disabled=is_locked)

    aliases_text = st.text_input(
        "Also known as (comma separated)",
        ",".join(case.get("entity_aliases") or []),
        help="Trading names, brands and abbreviations sources actually use - "
             "for example HypoVereinsbank and HVB for UniCredit's German bank. "
             "Without these, research searches only the registered legal name "
             "and the perimeter check discards every source that uses the "
             "brand.", disabled=is_locked)

    c4, c5, c6 = st.columns(3)
    _perimeter_options = ["SINGLE_ENTITY", "GROUP_CONSOLIDATED", "NAMED_SUBSIDIARIES",
                          "NAMED_DIVISION"]
    _current_perimeter = case.get("group_perimeter")
    perimeter = c4.selectbox(
        "Group perimeter *", _perimeter_options,
        index=(_perimeter_options.index(_current_perimeter)
              if _current_perimeter in _perimeter_options else 0),
        disabled=is_locked)

    countries_text, region_choice = None, None
    if scope_mode == "COUNTRIES":
        countries_text = c5.text_input(
            "In-scope countries * (comma separated ISO codes)",
            ",".join(case.get("in_scope_countries") or []))
    elif scope_mode == "REGION":
        _default_region = _current_region if _current_region in region_options \
            else (region_options[0] if region_options else None)
        region_choice = c5.selectbox(
            "Region *", region_options,
            index=region_options.index(_default_region) if _default_region in region_options else 0)
    else:
        c5.caption("Resolves to every country with an approved pricing "
                   "benchmark, evaluated when you save.")

    layers = c6.multiselect("In-scope cost layers *", ["L0", "L1", "L2", "L3", "L4", "OPS"],
                            case.get("in_scope_cost_layers") or ["L0", "L2", "L4", "OPS"])

    c7, c8, c9 = st.columns(3)
    families = c7.text_input("In-scope service families *",
                             ",".join(case.get("in_scope_service_families") or ["WAN", "SSE"]))
    currency = c8.text_input("Base currency *", case.get("base_currency") or "USD", max_chars=3)
    price_year = c9.number_input("Price year *", 2020, 2035, case.get("price_year") or 2026)

    c10, c11, c12 = st.columns(3)
    horizon = c10.number_input("Analysis horizon (years) *", 1, 10,
                               case.get("analysis_horizon_years") or 5)
    drs = c11.text_input("Discount rate set *", case.get("discount_rate_set_id") or "DRS-2026-USD")
    contact = c12.selectbox("Client contact status *",
                            ["NO_CONTACT", "AWARE", "PARTICIPATING"])

    excluded = st.text_input("Known-but-excluded entities (comma separated)",
                             help="Stored explicitly, not merely omitted, so out-of-perimeter "
                                  "facts can be recognised and quarantined")

    if st.form_submit_button("Save intake block"):
        payload = {
            "scope_mode": scope_mode,
            "entity_aliases": [a.strip() for a in aliases_text.split(",") if a.strip()],
            "in_scope_countries": ([c.strip().upper() for c in countries_text.split(",") if c.strip()]
                                   if countries_text else []),
            "region": region_choice,
            "in_scope_cost_layers": layers,
            "in_scope_service_families": [f.strip() for f in families.split(",") if f.strip()],
            "base_currency": currency or None,
            "price_year": int(price_year),
            "analysis_horizon_years": int(horizon),
            "discount_rate_set_id": drs or None,
            "client_contact_status": contact,
        }
        if not is_locked:
            # Only sent pre-confirmation: once entity_resolution.confirm() has
            # run, the backend refuses these four - they're re-set only by
            # confirming again, which is what actually advances
            # perimeter_version and re-stamps who confirmed what.
            payload["subject_entity_legal_name"] = name or None
            payload["entity_identifier"] = ident or None
            payload["country_of_domicile"] = dom or None
            payload["group_perimeter"] = perimeter
        r = api.put(f"/v1/outside-in/cases/{case_id}", payload)
        if "_error" in r:
            st.error(r["_error"])
        else:
            resolved = r.get("in_scope_countries") or []
            st.success(f"Intake block saved. In-scope countries resolved to: "
                      f"{', '.join(resolved) if resolved else '(none - no approved '
                      f'priors matched this selection)'}")
            st.rerun()

st.divider()
st.subheader("Is this the company you meant?")
st.caption("A short current profile of the subject, searched fresh. It writes "
           "nothing and confirms nothing - it is here so you can see the "
           "company the system is about to research before it starts. A "
           "registered legal name is often not what sources call an entity, "
           "and that mismatch is invisible until every source has been "
           "discarded as being about someone else.")

if st.button("Look up this entity",
             disabled=not (case.get("subject_entity_legal_name") or "").strip()):
    with st.spinner("Searching public sources..."):
        st.session_state["_profile"] = api.post(
            f"/v1/outside-in/cases/{case_id}/entity:profile", {},
            timeout=300.0)

_prof = st.session_state.get("_profile")
if _prof and "_error" in _prof:
    st.error(_prof["_error"])
elif _prof:
    if _prof.get("abstention_reason"):
        st.warning(f"The entity could not be identified from public sources "
                   f"({_prof['abstention_reason']}). That is itself worth "
                   f"knowing: check the spelling and the legal form before "
                   f"researching anything.")
    else:
        if not _prof.get("name_matches_supplied"):
            st.warning(
                f"**The name you entered and the name sources use do not "
                f"match.** You entered *{_prof.get('name_as_supplied')}*; "
                f"sources call it *{_prof.get('legal_name_as_sources_state')}*. "
                f"That is not necessarily wrong - a trading name is normal - "
                f"but it is the point at which to check the perimeter.")

        st.markdown(f"**{_prof.get('legal_name_as_sources_state') or 'Subject'}**"
                    + (f" — {_prof.get('parent_or_group')}"
                       if _prof.get("parent_or_group") else ""))
        st.write(_prof.get("what_it_is") or "")
        st.write(_prof.get("what_is_current") or "")

        if _prof.get("disambiguation_note"):
            st.info(f"**More than one entity could be meant.** "
                    f"{_prof['disambiguation_note']}")

        _proposed = _prof.get("also_known_as") or []
        if _proposed:
            st.markdown("**Also known as**")
            st.caption("The perimeter check and every research search read "
                       "these. Without them a source using the brand is "
                       "discarded as being about a different company.")
            keep = st.multiselect("Aliases to record", _proposed,
                                  default=_proposed, key="alias_pick")
            if st.button("Add these aliases to the case", disabled=not keep):
                merged = sorted(set((case.get("entity_aliases") or []) + keep))
                r = api.put(f"/v1/outside-in/cases/{case_id}",
                            {"entity_aliases": merged})
                if "_error" in r:
                    st.error(r["_error"])
                else:
                    st.success(f"{len(merged)} alias(es) recorded.")
                    st.rerun()

        if _prof.get("identifiers"):
            st.caption("Identifiers found: " + ", ".join(_prof["identifiers"]))
        with st.expander("Sources"):
            for src in _prof.get("sources") or []:
                st.write(f"- {src.get('publisher') or 'source'}: "
                         f"{src.get('url')}"
                         + (f" ({src['as_of']})" if src.get("as_of") else ""))
        st.caption(_prof.get("note", ""))

st.divider()
st.subheader("Subject-entity resolution")
st.caption("The system proposes; you dispose. Auto-selection is prohibited even when "
           "only one candidate is returned.")

col1, col2 = st.columns([3, 1])
hint = col1.text_input("Name as supplied", name or "")
provider = col2.selectbox("Provider", ["anthropic", "openai"])

if st.button("Generate candidates (LIVE agent run)", type="primary", disabled=not hint):
    with st.spinner("Calling provider..."):
        r = api.post(f"/v1/outside-in/cases/{case_id}/entities:resolve",
                     {"name_hint": hint, "identifier_hint": ident or None,
                      "provider": provider, "mode": "LIVE"})
    if "_error" in r:
        st.error(f"**Run failed closed.** {r['_error']}")
        st.caption("No candidates were fabricated. This is the intended behaviour when a "
                   "provider is unavailable (7.2B).")
    else:
        p = r["provenance"]
        st.success(f"{len(r['candidates'])} candidates. Provider response "
                   f"`{p['provider_response_id']}` - {p['input_tokens']} in / "
                   f"{p['output_tokens']} out tokens, {p['latency_ms']} ms.")

cands = api.get(f"/v1/outside-in/cases/{case_id}/entity-candidates").get("candidates", [])
if cands:
    st.markdown("**Candidates** - review the differentiators before confirming.")
    for c in cands:
        with st.expander(f"{c['legal_name']} ({c['domicile'] or '??'}) - "
                         f"match {c['match_score']}"):
            st.write({k: c[k] for k in ("identifier", "industry", "revenue", "employees",
                                        "group_parent", "website")})
            st.caption((c.get("sources") or {}).get("differentiator") or "")
            who = st.text_input("Confirmed by (your name)", key=f"who_{c['candidate_id']}")
            if st.button("Confirm this entity", key=f"cf_{c['candidate_id']}", disabled=not who):
                r = api.post(f"/v1/outside-in/cases/{case_id}:confirm-entity",
                             {"candidate_id": c["candidate_id"], "confirmed_by": who,
                              "group_perimeter": perimeter,
                              "excluded_entities": [x.strip() for x in excluded.split(",") if x.strip()]})
                if "_error" in r:
                    st.error(r["_error"])
                else:
                    st.success(f"Confirmed {r['legal_name']} - perimeter v{r['perimeter_version']}")
                    st.rerun()

if case.get("resolved_entity_id"):
    st.success(f"**Resolved:** {case['subject_entity_legal_name']} - confirmed by "
               f"{case['entity_confirmed_by']}, perimeter v{case['perimeter_version']}")
