"""Fleet Copilot – Streamlit chat interface.

Run:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from fleet_copilot.charts import suggest_chart
from fleet_copilot.copilot import Answer, FleetCopilot

st.set_page_config(page_title="Fleet Copilot", page_icon="🚚", layout="wide")

SAMPLE_QUESTIONS = [
    "Which vehicles are underperforming this month?",
    "Who are the 10 riskiest drivers last month?",
    "Which vehicles are overdue for service?",
    "Estimated idle cost per customer in September",
    "Compare fuel bought vs fuel used and flag big gaps",
    "Show total distance driven per month",
    "Cost per km for each customer this quarter",
]


@st.cache_resource(show_spinner="Loading knowledge base…")
def get_copilot() -> FleetCopilot:
    return FleetCopilot()


@st.cache_data(show_spinner=False)
def fleet_kpis() -> dict:
    db = get_copilot().db
    q = db.run("""
        SELECT (SELECT COUNT(*) FROM customers) AS customers,
               (SELECT COUNT(*) FROM vehicles WHERE status='active') AS active_vehicles,
               (SELECT ROUND(SUM(distance_km)) FROM trips WHERE trip_date >= '2026-09-01') AS km_sep,
               (SELECT ROUND(SUM(distance_km)/SUM(fuel_used_l),2) FROM trips WHERE trip_date >= '2026-09-01') AS kmpl_sep,
               (SELECT ROUND(SUM(idle_min)*100.0/SUM(duration_min),1) FROM trips WHERE trip_date >= '2026-09-01') AS idle_sep
    """)
    return q.iloc[0].to_dict()


def render_answer(ans: Answer) -> None:
    if ans.error:
        st.error(ans.error)
    if ans.summary:
        st.markdown(ans.summary)
    if ans.ok:
        df = ans.data
        if df.empty:
            st.info("The query ran but returned no rows.")
        else:
            spec = suggest_chart(df)
            if spec:
                chart_df = df.set_index(spec.x)[spec.y]
                (st.line_chart if spec.kind == "line" else st.bar_chart)(chart_df, height=280)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode(), "fleet_copilot_result.csv",
                               "text/csv", key=f"dl-{id(ans)}")
    if ans.sql or ans.steps:
        with st.expander("How I got this answer"):
            if ans.sql:
                st.code(ans.sql, language="sql")
            cols = st.columns(3)
            cols[0].metric("Total time", f"{ans.total_ms / 1000:.2f}s")
            cols[1].metric("SQL attempts", ans.attempts)
            cols[2].metric("Tokens", f"{ans.input_tokens + ans.output_tokens:,}")
            st.caption(" · ".join(f"{s.name} {s.ms:.0f} ms" for s in ans.steps))
            if ans.definitions_used:
                st.caption("KPI definitions used: " + ", ".join(ans.definitions_used))
            if ans.examples_used:
                st.caption("Similar verified examples: " + " | ".join(ans.examples_used[:3]))


copilot = get_copilot()

with st.sidebar:
    st.title("🚚 Fleet Copilot")
    st.caption("Ask questions about your fleet in plain English.")
    mode = copilot.mode
    if mode == "offline":
        st.warning("Offline demo mode: answers only questions close to the example library. "
                   "Set ANTHROPIC_API_KEY or OPENAI_API_KEY for full mode.")
    else:
        st.success(f"Model: {mode}")
    st.caption(f"Retriever: {copilot.kb.backend}")
    st.divider()
    st.subheader("Try asking")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True):
            st.session_state.pending = q
    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state.history = []
    st.caption("Data: synthetic UAE fleet dataset, Jul–Sep 2026.")

k = fleet_kpis()
c = st.columns(5)
c[0].metric("Customers", int(k["customers"]))
c[1].metric("Active vehicles", int(k["active_vehicles"]))
c[2].metric("Distance (Sep)", f"{k['km_sep']:,.0f} km")
c[3].metric("Fuel efficiency (Sep)", f"{k['kmpl_sep']} km/L")
c[4].metric("Idle time (Sep)", f"{k['idle_sep']}%")
st.divider()

st.session_state.setdefault("history", [])
for item in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(item.question)
    with st.chat_message("assistant"):
        render_answer(item)

prompt = st.chat_input("e.g. Which drivers had the most harsh braking in September?")
prompt = prompt or st.session_state.pop("pending", None)
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            ans = copilot.ask(prompt)
        render_answer(ans)
    st.session_state.history.append(ans)
