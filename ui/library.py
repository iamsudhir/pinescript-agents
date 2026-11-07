"""Library page: every saved strategy with its latest results; click a row to open it."""
import pandas as pd
import streamlit as st

from workbench import db

conn = db.connect()
st.title("Strategy library")

c1, c2, c3 = st.columns([3, 1, 1])
search = c1.text_input("Search by name")
status = c2.selectbox("Status", ["all", *db.STATUSES])
min_rating = c3.selectbox("Min rating", [0, 1, 2, 3, 4, 5], format_func=lambda r: "any" if r == 0 else "★" * r)

rows = db.list_strategies(conn, status=None if status == "all" else status,
                          min_rating=min_rating or None, search=search or None)
if not rows:
    st.info("No strategies yet. Make one on the **Create** page.")
    st.stop()


def stat(r, key):
    v = (r["latest_stats"] or {}).get(key)
    return float("nan") if v is None else v


table = pd.DataFrame([{
    "Name": r["name"], "Status": r["status"], "Rating": "★" * (r["rating"] or 0), "Source": r["source_type"],
    "Runs": r["n_runs"], "Return %": stat(r, "Return [%]"), "Sharpe": stat(r, "Sharpe Ratio"),
    "Max DD %": stat(r, "Max. Drawdown [%]"),
    "Latest optimization": f'{r["opt_maximize"]} {r["opt_best"]:.2f}' if r["opt_best"] is not None else "",
    "Created": r["created_at"][:10],
} for r in rows])
st.caption("Stats are from each strategy's latest run. Click a row to open the strategy.")
event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.2f")
                                    for c in ("Return %", "Sharpe", "Max DD %")})
if event.selection.rows:
    st.session_state.strategy_id = rows[event.selection.rows[0]]["id"]
    st.switch_page("ui/strategy.py")
