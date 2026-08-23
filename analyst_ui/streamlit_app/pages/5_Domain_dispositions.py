import pandas as pd
import streamlit as st
import api_client as api

st.title("5. Domain dispositions")
st.caption("Specification 0.3A - maximalist means every in-scope input domain carries a "
           "recorded disposition, not that the search ran longer.")

case_id = st.session_state.get("case_id")
if not case_id:
    st.warning("Select a case on the home page first."); st.stop()

current = api.get(f"/v1/outside-in/cases/{case_id}/domain-dispositions")
catalogue = current.get("catalogue", [])
existing = {d["domain_no"]: d for d in current.get("dispositions", [])}

DISPOSITIONS = ["EVIDENCED_PUBLIC", "DERIVED_PUBLIC", "BENCHMARK_PRIOR",
                "ANALYST_ASSERTED_PRIOR", "SIMULATED", "DECLARED_UNKNOWN"]
REASONS = ["", "NO_PUBLIC_EVIDENCE", "BUDGET_EXHAUSTED", "OUT_OF_PERIMETER",
           "CONFLICTING_EVIDENCE_UNRESOLVED", "NOT_APPLICABLE"]

rows = [{"domain_no": n, "domain_name": nm,
         "disposition": existing.get(n, {}).get("disposition", "BENCHMARK_PRIOR"),
         "reason": existing.get(n, {}).get("reason") or ""} for n, nm in catalogue]

edited = st.data_editor(
    pd.DataFrame(rows), use_container_width=True, hide_index=True, height=520,
    column_config={
        "domain_no": st.column_config.NumberColumn("#", disabled=True, width="small"),
        "domain_name": st.column_config.TextColumn("Input domain", disabled=True, width="large"),
        "disposition": st.column_config.SelectboxColumn("Disposition", options=DISPOSITIONS),
        "reason": st.column_config.SelectboxColumn("Reason (DECLARED_UNKNOWN only)",
                                                   options=REASONS)})

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
