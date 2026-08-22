import os
from decimal import Decimal

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Network Cost Workbench", layout="wide")
st.title("Enterprise Network Cost Transformation Workbench")
st.caption("Initial Stage 0 analyst interface — API only, no direct database or model access")

with st.sidebar:
    st.subheader("Control plane")
    st.code(API_BASE_URL)
    try:
        health = httpx.get(f"{API_BASE_URL}/health", timeout=5).json()
        st.success(f"API {health['status']} · v{health['version']}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"API unavailable: {exc}")

st.header("Stage 0 savings estimate")
left, right = st.columns(2)
with left:
    current = st.number_input("Estimated current annual TCO", min_value=0.0, value=10_000_000.0)
with right:
    target = st.number_input("Estimated target annual TCO", min_value=0.0, value=7_500_000.0)

currency = st.selectbox("Currency", ["USD", "EUR", "GBP", "AED"])

if st.button("Calculate", type="primary"):
    payload = {
        "current_tco": str(Decimal(str(current))),
        "target_tco": str(Decimal(str(target))),
        "currency": currency,
    }
    response = httpx.post(
        f"{API_BASE_URL}/v1/calculations/savings",
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    a, b, c = st.columns(3)
    a.metric("Current TCO", f"{currency} {Decimal(data['current_tco']):,.0f}")
    b.metric("Target TCO", f"{currency} {Decimal(data['target_tco']):,.0f}")
    c.metric(
        "Run-rate savings",
        f"{currency} {Decimal(data['savings']):,.0f}",
        f"{data['savings_rate_percent']}%",
    )
    st.info("V0 is an outside-in estimate. Later versions replace it; they do not add to it.")
