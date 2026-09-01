import pandas as pd
import streamlit as st
import api_client as api

st.title("10. Benchmark vault and reference data")
st.caption(
    "Specification 5.6 - where a published cost figure becomes a price band "
    "the estimate may use. Four endpoints implemented this workflow and no "
    "screen called any of them, so the only way to ingest a source, clear its "
    "rights or derive a band was to run a script - and the governance an "
    "external audit called bypassable was governance nobody could reach.")
api.show_flash()

st.info(
    "**This is a steward screen, not a case screen.** Everything here is "
    "reference data shared by every case: a band derived once prices every "
    "estimate that matches it. Nothing on this page belongs to the case "
    "selected on the home page.")

# ---------------------------------------------------------------- 1. ingest
st.divider()
st.subheader("Ingest a published source")
st.caption(
    "The text is sent to LLM-09, which extracts observations. Nothing it "
    "returns is a price the estimate can use: an observation lands in the "
    "vault un-cleared and unapproved, and becomes usable only after a named "
    "person clears its rights and a band is derived from enough of them.")

_c1, _c2 = st.columns(2)
_doc = _c1.text_input(
    "Source document *", key="bm_doc",
    help="What this is, as a reader would cite it - the report title and year.")
_org = _c2.text_input("Publisher", key="bm_org")
_c3, _c4, _c5 = st.columns(3)
_loc = _c3.text_input("Locator", key="bm_loc",
                      help="Page, table or section, so a reader can check it.")
_asof = _c4.text_input("As of", key="bm_asof", placeholder="2025 or 2025-06-30")
_rights = _c5.selectbox(
    "Rights basis", ["PUBLISHED", "LICENSED", "CLIENT_SUPPLIED", "UNCLEAR"],
    key="bm_rights",
    help="PUBLISHED means publicly available and quotable. Anything else "
         "cannot be cleared on this screen.")
_text = st.text_area(
    "Source text *", key="bm_text", height=200,
    help="Paste the passage carrying the figures. Convert a PDF locally - only "
         "the text is sent, never the file.")

if st.button("Extract observations", type="primary",
             disabled=not (_text.strip() and _doc.strip())):
    with st.spinner("LLM-09 reading the source..."):
        st.session_state["_bm_extract"] = api.post(
            "/v1/benchmarks:extract",
            {"text": _text, "source_document": _doc,
             "source_locator": _loc or None, "source_org": _org or None,
             "rights_basis": _rights, "as_of": _asof or None},
            timeout=300.0)

_ex = st.session_state.get("_bm_extract")
if _ex and "_error" in _ex:
    st.error(_ex["_error"])
    # A rejected extraction still returns its observations rather than
    # discarding them, so a steward does not pay for a second provider call to
    # see what the first one said.
    for _o in (_ex.get("observations") or []):
        st.caption(f"   salvaged: {_o}")
    if _ex.get("note"):
        st.warning(_ex["note"])
elif _ex:
    st.success(f"{len(_ex.get('observations') or [])} observation(s) stored "
               f"un-cleared and unapproved.")
    if _ex.get("unresolved_questions"):
        st.markdown("**The extraction could not settle these**")
        for _q in _ex["unresolved_questions"]:
            st.caption(f"   {_q}")

# ------------------------------------------------------------ 2. the vault
st.divider()
st.subheader("The vault")

_f1, _f2, _f3 = st.columns(3)
_metric = _f1.text_input("Metric contains", key="bm_fmetric")
_country = _f2.text_input("Country", key="bm_fcountry", max_chars=2)
_cleared = _f3.selectbox("Rights", ["any", "cleared", "not cleared"],
                         key="bm_fcleared")

_params = []
if _metric.strip():
    _params.append(f"metric={_metric.strip()}")
if _country.strip():
    _params.append(f"country={_country.strip().upper()}")
if _cleared != "any":
    _params.append(f"rights_cleared={'true' if _cleared == 'cleared' else 'false'}")
_obs = api.get("/v1/benchmarks/observations"
               + ("?" + "&".join(_params) if _params else ""))

if "_error" in _obs:
    st.error(_obs["_error"])
    _rows = []
else:
    _rows = _obs.get("observations") or []

if not _rows:
    st.info("No observation matches. Ingest a source above, or widen the "
            "filter.")
else:
    st.caption(f"{len(_rows)} observation(s).")
    _cols = [c for c in ("observation_id", "metric", "country", "product",
                         "bandwidth_mbps", "value", "currency", "as_of",
                         "source_document", "rights_basis", "rights_cleared",
                         "cleared_by")
             if _rows and c in _rows[0]]
    st.dataframe(pd.DataFrame(_rows)[_cols], use_container_width=True,
                 hide_index=True)

    # ------------------------------------------------------ 3. clear rights
    _uncleared = [r for r in _rows if not r.get("rights_cleared")]
    if _uncleared:
        st.markdown("**Clear rights**")
        st.caption(
            "Clearing attests that this figure may be reused in a client "
            "deliverable. It is a named act and it is what stands between a "
            "published number and an estimate quoting it - so it is not a "
            "checkbox on ingestion.")
        _pick = st.multiselect(
            "Observations to clear",
            [r["observation_id"] for r in _uncleared],
            format_func=lambda oid: next(
                (f"{r.get('metric')} {r.get('country') or ''} "
                 f"{r.get('value')} - {r.get('source_document')}"
                 for r in _uncleared if r["observation_id"] == oid), oid),
            key="bm_clear_pick")
        _by = st.text_input("Clearing as (your name)", key="bm_clear_by")
        if st.button("Clear rights on the selected",
                     disabled=not (_pick and _by.strip())):
            _r = api.post("/v1/benchmarks/observations:clear-rights",
                          {"observation_ids": _pick, "cleared_by": _by})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash(f"{len(_pick)} observation(s) cleared by {_by}.")
                st.rerun()

# --------------------------------------------------------- 4. derive bands
st.divider()
st.subheader("Derive price bands")
st.caption(
    "A band is built from cleared observations only, and needs enough of them "
    "to be a band rather than a point. Derive as a dry run first: it reports "
    "what would be written without writing it.")

_d1, _d2, _d3 = st.columns(3)
_cur = _d1.text_input("Currency", value="USD", key="bm_cur", max_chars=3)
_year = _d2.number_input("Price year", 2020, 2035, 2026, key="bm_year")
_minobs = _d3.number_input(
    "Minimum observations", 1, 20, 3, key="bm_minobs",
    help="Below three, the low and high are the two figures you happen to "
         "have rather than a range.")

_g1, _g2 = st.columns(2)
if _g1.button("Dry run"):
    st.session_state["_bm_bands"] = api.post(
        "/v1/benchmarks/bands:derive",
        {"currency": _cur.upper(), "price_year": int(_year),
         "min_observations": int(_minobs), "dry_run": True}, timeout=120.0)
if _g2.button("Derive and write", type="primary"):
    st.session_state["_bm_bands"] = api.post(
        "/v1/benchmarks/bands:derive",
        {"currency": _cur.upper(), "price_year": int(_year),
         "min_observations": int(_minobs), "dry_run": False}, timeout=120.0)

_bd = st.session_state.get("_bm_bands")
if _bd and "_error" in _bd:
    st.error(_bd["_error"])
elif _bd:
    _written = _bd.get("bands") or _bd.get("derived") or []
    (st.info if _bd.get("dry_run") else st.success)(
        f"{len(_written)} band(s) "
        + ("would be written - nothing has been."
           if _bd.get("dry_run") else "written."))
    if _written:
        st.dataframe(pd.DataFrame(_written), use_container_width=True,
                     hide_index=True)
    for _skip in _bd.get("skipped") or []:
        st.caption(f"   skipped: {_skip}")

# ------------------------------------------------------- 5. research briefs
st.divider()
st.subheader("Research briefs")
st.caption(
    "What each domain's agent is asked to find. Governed reference data with a "
    "version and an approver, editable here rather than only in code - a brief "
    "tuned for a bank and left in place for a distributor is how a domain "
    "quietly stops finding anything.")

_briefs = api.get("/v1/reference/research-briefs")
if "_error" in _briefs:
    st.error(_briefs["_error"])
else:
    _bl = _briefs.get("briefs") or []
    st.caption(f"{len(_bl)} active brief(s).")
    _sel = st.selectbox(
        "Domain", [b["domain_no"] for b in _bl],
        format_func=lambda n: next(
            (f"{n}. {b.get('domain_name') or b.get('asks','')[:50]}"
             for b in _bl if b["domain_no"] == n), str(n)),
        key="bm_brief_pick")
    _b = next((b for b in _bl if b["domain_no"] == _sel), None)
    if _b:
        _asks = st.text_area("Asks", value=_b.get("asks") or "",
                             key="bm_asks", height=90)
        _wants = st.text_area("Wants", value=_b.get("wants") or "",
                              key="bm_wants", height=90)
        _search = st.text_area(
            "Search patterns, one per line",
            value="\n".join(_b.get("search") or []), key="bm_search",
            height=90,
            help="{entity} is substituted, and multiplied across the case's "
                 "aliases - which is what makes a trading name findable.")
        _sources = st.text_area(
            "Preferred sources, one per line",
            value="\n".join(_b.get("sources") or []), key="bm_sources",
            height=70)
        _e1, _e2 = st.columns(2)
        _ver = _e1.text_input("New brief version *", key="bm_ver",
                              placeholder=str(_b.get("brief_version") or "1.0.0"))
        _appr = _e2.text_input("Approved by *", key="bm_appr")
        if st.button("Publish this brief",
                     disabled=not (_ver.strip() and _appr.strip())):
            _r = api.put(f"/v1/reference/research-briefs/{_sel}", {
                "asks": _asks, "wants": _wants or None,
                "search": [l.strip() for l in _search.splitlines() if l.strip()],
                "sources": [l.strip() for l in _sources.splitlines() if l.strip()],
                "example": _b.get("example"), "reject": _b.get("reject"),
                "brief_version": _ver, "approved_by": _appr})
            if "_error" in _r:
                st.error(_r["_error"])
            else:
                api.flash(f"Brief for domain {_sel} published as {_ver} by "
                          f"{_appr}. The plan version hash changes with it, so "
                          f"a run made before this is distinguishable from one "
                          f"made after.")
                st.rerun()
