"""Strategy page: code, backtest, optimize, history and insights for one strategy."""
import datetime as dt
import json
import traceback

import altair as alt
import pandas as pd
import streamlit as st

from workbench import actions, data, db, engine, generate, insights

conn = db.connect()
MIN_DATE = dt.date(1990, 1, 1)
state = st.session_state
sid = state.get("strategy_id")
s = db.get_strategy(conn, sid) if sid else None
if not s:
    st.info("Open a strategy from the **Library** page.")
    st.stop()

state.setdefault("form_gen", 0)
if state.get("market_for") != sid:  # market settings belong to one strategy: start from its defaults
    state.market_for = sid
    state.form_gen += 1  # fresh widget keys, so the old strategy's typed values are not reused
    state.market = {
        "ticker": s["default_ticker"], "interval": s["default_interval"],
        "start": dt.date.fromisoformat(data.default_start(s["default_interval"])), "end": dt.date.today(),
        "cash": 1_000_000.0, "commission": 0.0005,
    }

# Buttons that load a run or parameters store a "goto" and rerun. A widget's value can't be
# changed once it is drawn, so the goto is applied here, and form_gen gives the form fresh
# widget keys so the new values show up.
goto = state.pop("goto", None)
if goto:
    state[f"cur_ver_{sid}"] = goto["version"]
    if "params" in goto:
        key = f"params_{goto['version']}"
        state[key] = {**state.get(key, {}), **goto["params"]}
    if "market" in goto:
        state.market = goto["market"]
    state.form_gen += 1
    st.toast(goto["message"])
gen = state.form_gen


def jump(version_id, message, params=None, market=None):
    state.goto = {"version": version_id, "message": message,
                  **({"params": params} if params else {}), **({"market": market} if market else {})}
    st.rerun()


def market_of(rec):
    return {"ticker": rec["ticker"], "interval": rec["interval"],
            "start": dt.date.fromisoformat(rec["start_date"]), "end": dt.date.fromisoformat(rec["end_date"]),
            "cash": rec["cash"], "commission": rec["commission"]}


def fmt(x):
    if x is None:
        return "-"
    return f"{x:,}" if isinstance(x, int) else f"{x:,.2f}".replace("-0.00", "0.00")


# --- header, version, market ----------------------------------------------------

st.title(s["name"])
st.caption(f'{s["source_type"]} · {s["source"] or "-"} · created {s["created_at"][:10]} · status: {s["status"]}')

versions = db.list_versions(conn, sid)
ids = [v["id"] for v in versions]
cur = state.get(f"cur_ver_{sid}", ids[0])
vid = st.selectbox("Code version", ids, index=ids.index(cur) if cur in ids else 0, key=f"ver_{sid}_{gen}",
                   format_func=lambda i: next(f'v{v["version"]} · {v["change_note"]} · {v["created_at"][:16]}'
                                              for v in versions if v["id"] == i))
state[f"cur_ver_{sid}"] = vid
v = db.get_version(conn, vid)

m = state.market
c = st.columns(6)
market = {
    "ticker": c[0].text_input("Ticker", m["ticker"], key=f"mk_ticker_{gen}",
                              help="NSE stock: RELIANCE.NS · Nifty 50: ^NSEI · Bank Nifty: ^NSEBANK · "
                                   "US: AAPL · crypto: BTC-USD").strip(),
    "interval": c[1].selectbox("Interval", data.INTERVALS, key=f"mk_interval_{gen}",
                               index=data.INTERVALS.index(m["interval"]) if m["interval"] in data.INTERVALS else 0,
                               help="yfinance keeps ~60 days of 5m-30m bars and ~2 years of 1h bars"),
    "start": c[2].date_input("Start", m["start"], min_value=MIN_DATE, max_value=dt.date.today(), key=f"mk_start_{gen}"),
    "end": c[3].date_input("End (exclusive)", m["end"], min_value=MIN_DATE, max_value=dt.date.today(),
                            key=f"mk_end_{gen}"),
    "cash": c[4].number_input("Cash", value=float(m["cash"]), step=100_000.0, key=f"mk_cash_{gen}"),
    "commission": c[5].number_input("Commission", value=float(m["commission"]), step=0.0001, format="%.4f",
                                    key=f"mk_comm_{gen}", help="Fraction per side: 0.0005 = 0.05%"),
}
if market["interval"] != m["interval"]:  # the old start may be out of range for the new interval
    state.market = {**market, "start": dt.date.fromisoformat(data.default_start(market["interval"]))}
    state.form_gen += 1
    st.rerun()
state.market = market
run_market = {**market, "start": market["start"].isoformat(), "end": market["end"].isoformat()}


# --- helpers shared by the tabs ------------------------------------------------------

def strategy_params(version):
    """The version's parameters, or None if its Python fails to load (kept for 'Fix with Claude')."""
    try:
        return engine.load_strategy(version["python_code"])[1]
    except engine.StrategyContractError as e:
        state.error = (version["id"], str(e))
        return None


def guarded(fn):
    """Run fn(): data problems are shown; code problems are kept for 'Fix with Claude'."""
    try:
        fn()
        state.pop("error", None)
    except data.DataError as e:
        st.error(str(e))
    except Exception:
        state.error = (vid, traceback.format_exc())


def fix_with_claude(pine, python, error):
    try:
        with st.spinner("Claude is fixing the code..."):
            fixed = generate.fix(pine, python, error)
    except Exception as e:
        st.error(f"Claude call failed: {e}")
        return
    new_vid = db.add_version(conn, sid, fixed.pine, fixed.python,
                             "fix with Claude: " + error.strip().splitlines()[-1][:80])
    db.update_strategy(conn, sid, notes=fixed.notes)
    state.pop("error", None)
    jump(new_vid, "Saved Claude's fix as a new version")


def show_error(where):
    err = state.get("error")
    if err and err[0] == vid:
        st.error("The Python strategy failed. Claude can fix it, or edit it in the Code tab.")
        st.code(err[1], language=None)
        if st.button("Fix with Claude", key=f"fix_{where}"):
            fix_with_claude(v["pine_code"], v["python_code"], err[1])


def show_run(run, where):
    st.markdown(f'**Run #{run["id"]}** · v{run["version"]} · {run["ticker"]} {run["interval"]} · '
                f'{run["start_date"]} -> {run["end_date"]}')
    cols = st.columns(5)
    for i, k in enumerate(engine.KEY_STATS):
        cols[i % 5].metric(k, fmt(run["stats"].get(k)))
    if run["equity"]:
        eq = pd.DataFrame(run["equity"], columns=["Time", "Equity"])
        eq["Time"] = pd.to_datetime(eq["Time"])
        st.line_chart(eq, x="Time", y="Equity")
    st.dataframe(pd.DataFrame(run["trades"]), hide_index=True)
    if st.button("Open full interactive chart", key=f"chart_{where}_{run['id']}"):
        guarded(lambda: st.iframe(actions.chart_for_run(conn, run["id"]), height=900))


def show_opt(opt, where):
    metric = opt["maximize"]
    res = pd.DataFrame(opt["results"])
    st.markdown(f'**Optimization #{opt["id"]}** · v{opt["version"]} · {opt["ticker"]} {opt["interval"]} · '
                f'{opt["start_date"]} -> {opt["end_date"]} · {len(res)} combinations')
    if opt["best_value"] is None:
        st.warning("No combination produced a result (no trades?).")
        return
    st.markdown(f'Best {metric} = **{opt["best_value"]:.3f}** with `{opt["best_params"]}`')
    names = [col for col in res.columns if col != metric]
    if len(names) == 2 and all(res[n].dtype != bool for n in names):
        st.altair_chart(alt.Chart(res.rename(columns={metric: "metric"})).mark_rect().encode(
            x=alt.X(f"{names[0]}:O"), y=alt.Y(f"{names[1]}:O"),
            color=alt.Color("metric:Q", title=metric), tooltip=[*names, "metric"]))
    picked = st.dataframe(res, hide_index=True, on_select="rerun", selection_mode="single-row",
                          key=f"optres_{where}_{opt['id']}")
    row = res.iloc[picked.selection.rows[0]].to_dict() if picked.selection.rows else opt["best_params"]
    if st.button("Load selected row (or best) into Backtest", key=f"use_{where}_{opt['id']}"):
        version = db.get_version(conn, opt["strategy_version_id"])
        try:
            defaults = engine.load_strategy(version["python_code"])[1]
        except engine.StrategyContractError as e:
            st.error(str(e))
            return
        params = {k: engine.coerce(row[k], defaults[k]) for k in names if k in defaults}
        jump(version["id"], "Parameters loaded: open the Backtest tab", params=params, market=market_of(opt))


code_tab, bt_tab, opt_tab, hist_tab, ins_tab = st.tabs(["Code", "Backtest", "Optimize", "History", "Insights"])

# --- Code ---------------------------------------------------------------------------

with code_tab:
    for w in generate.lint_pine(v["pine_code"]):
        st.warning(f"Pine check: {w}")
    if s["notes"]:
        with st.expander(f'Where Pine and Python may differ ({len(s["notes"])} notes)'):
            st.markdown("\n".join(f"- {n}" for n in s["notes"]))
    left, right = st.columns(2)
    pine = left.text_area("Pine Script v6: paste into TradingView", v["pine_code"], height=520, key=f"pine_{vid}")
    python = right.text_area("Python: backtesting.py", v["python_code"], height=520, key=f"py_{vid}")
    left.download_button("Download .pine", pine, f'{s["slug"]}.pine', key="dl_pine")
    right.download_button("Download .py", python, f'{s["slug"]}.py', key="dl_py")
    with left.expander("Pine with a copy button"):
        st.code(pine, language=None)
    if st.button("Save edits as a new version"):
        if (pine, python) == (v["pine_code"], v["python_code"]):
            st.info("No changes to save.")
        else:
            jump(db.add_version(conn, sid, pine, python, "manual edit"), "Saved as a new version")
    error = st.text_area("Paste an error for Claude to fix (TradingView compiler error or Python traceback)",
                         key=f"err_{vid}")
    if st.button("Fix with Claude", key="fix_code"):
        if error.strip():
            fix_with_claude(pine, python, error)
        else:
            st.warning("Paste an error first.")

# --- Backtest -----------------------------------------------------------------------

with bt_tab:
    params = strategy_params(v)
    if params is not None:
        saved = state.get(f"params_{vid}", {})
        cols = st.columns(4)
        chosen = {}
        for i, (k, d) in enumerate(params.items()):
            val, key = engine.coerce(saved.get(k, d), d), f"p_{vid}_{gen}_{k}"
            if isinstance(d, bool):
                chosen[k] = cols[i % 4].checkbox(k, val, key=key)
            elif isinstance(d, int):
                chosen[k] = cols[i % 4].number_input(k, value=val, step=1, key=key)
            else:
                chosen[k] = cols[i % 4].number_input(k, value=val, format="%g", key=key)
        state[f"params_{vid}"] = chosen
        if st.button("Run backtest", type="primary"):
            def go():
                with st.spinner("Loading data and running the backtest..."):
                    state.view_run = actions.backtest(conn, vid, run_market, chosen)[0]
            guarded(go)
    show_error("bt")
    run = db.get_run(conn, state["view_run"]) if state.get("view_run") else None
    if run and run["strategy_id"] == sid:
        show_run(run, "bt")

# --- Optimize -----------------------------------------------------------------------

with opt_tab:
    params = strategy_params(v)
    if params is not None:
        st.caption("Tick the parameters to vary; the others keep their defaults. "
                   "Grids over 500 combinations are randomly sampled down to 500.")
        ranges = {}
        for k, d in params.items():
            row = st.columns([2, 1, 1, 1])
            if not row[0].checkbox(k, key=f"o_{vid}_p_{k}"):
                continue
            if isinstance(d, bool):
                row[1].caption("tries False and True")
                ranges[k] = (0, 1, 1)
                continue
            lo, hi, step = engine.default_range(d)
            f = None if isinstance(d, int) else "%g"
            ranges[k] = (row[1].number_input("min", value=lo, format=f, key=f"o_{vid}_p_{k}_lo"),
                         row[2].number_input("max", value=hi, format=f, key=f"o_{vid}_p_{k}_hi"),
                         row[3].number_input("step", value=step, format=f, key=f"o_{vid}_p_{k}_step"))
        maximize = st.selectbox("Maximize", engine.MAXIMIZE, key=f"o_{vid}_maximize")
        n = engine.grid_size(ranges, params)
        if st.button(f"Run optimization ({n} combinations)", type="primary"):
            if n == 0:
                st.warning("Tick at least one parameter with a non-empty range.")
            else:
                def go():
                    with st.spinner("Optimizing..."):
                        state.view_opt = actions.optimize(conn, vid, run_market, ranges, maximize)[0]
                guarded(go)
    show_error("opt")
    opt = db.get_optimization(conn, state["view_opt"]) if state.get("view_opt") else None
    if opt and opt["strategy_id"] == sid:
        show_opt(opt, "opt")

# --- History ------------------------------------------------------------------------

with hist_tab:
    runs = db.list_runs(conn, sid)
    st.subheader(f"Backtest runs ({len(runs)})")
    if runs:
        table = pd.DataFrame([{
            "Run": r["id"], "Ver": r["version"], "Ticker": r["ticker"], "Interval": r["interval"],
            "From": r["start_date"], "To": r["end_date"], "Params": json.dumps(r["params"]),
            **{k: r["stats"].get(k) for k in ("Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]",
                                              "# Trades")},
            "Note": r["note"] or "", "When": r["created_at"][:16],
        } for r in runs])
        rows = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="multi-row",
                            key=f"hist_runs_{sid}_{len(runs)}").selection.rows
        picked = [runs[i] for i in rows]
        if len(picked) == 1:
            r = picked[0]
            note = st.text_input("Note for this run", r["note"] or "", key=f"rnote_{r['id']}")
            b1, b2 = st.columns(2)
            if b1.button("Save note", key="save_rnote"):
                db.set_note(conn, "runs", r["id"], note)
                st.rerun()
            if b2.button("Load into Backtest tab", key="load_run"):
                state.view_run = r["id"]
                jump(r["strategy_version_id"], f"Run #{r['id']} loaded into the Backtest tab",
                     params=r["params"], market=market_of(r))
        elif len(picked) > 1:
            st.markdown("**Compare runs**")
            compare = pd.DataFrame({f'#{r["id"]} {r["ticker"]} {r["interval"]}':
                                    {**r["stats"], **{f"param {k}": x for k, x in r["params"].items()}}
                                    for r in picked})
            st.dataframe(compare.map(lambda x: f"{x:,.2f}" if isinstance(x, float) else str(x)))

    opts = db.list_optimizations(conn, sid)
    st.subheader(f"Optimizations ({len(opts)})")
    if opts:
        otable = pd.DataFrame([{
            "Opt": o["id"], "Ver": o["version"], "Ticker": o["ticker"], "Interval": o["interval"],
            "From": o["start_date"], "To": o["end_date"], "Maximize": o["maximize"], "Best": o["best_value"],
            "Best params": json.dumps(o["best_params"]), "Note": o["note"] or "", "When": o["created_at"][:16],
        } for o in opts])
        sel = st.dataframe(otable, hide_index=True, on_select="rerun", selection_mode="single-row",
                           key=f"hist_opts_{sid}_{len(opts)}").selection.rows
        if sel:
            o = db.get_optimization(conn, opts[sel[0]]["id"])
            note = st.text_input("Note for this optimization", o["note"] or "", key=f"onote_{o['id']}")
            if st.button("Save note", key="save_onote"):
                db.set_note(conn, "optimizations", o["id"], note)
                st.rerun()
            show_opt(o, "hist")

# --- Insights -----------------------------------------------------------------------

with ins_tab:
    c1, c2 = st.columns(2)
    status = c1.selectbox("Status", db.STATUSES, index=db.STATUSES.index(s["status"]), key=f"status_{sid}")
    rating = c2.select_slider("Rating", options=[0, 1, 2, 3, 4, 5], value=s["rating"] or 0, key=f"rating_{sid}",
                              format_func=lambda r: "unrated" if r == 0 else "★" * r)
    notes = st.text_area("My notes", s["user_notes"] or "", height=150, key=f"notes_{sid}",
                         placeholder="What works, what doesn't, ideas to try...")
    if (status, rating or None, notes) != (s["status"], s["rating"], s["user_notes"] or ""):
        db.update_strategy(conn, sid, status=status, rating=rating or None, user_notes=notes)
        st.toast("Saved")

    st.subheader("Summary of all runs")
    sm = insights.summary(conn, sid)
    if not sm["n_runs"]:
        st.info("No runs yet. Backtest the strategy to build up a summary.")
    else:
        mc = st.columns(4)
        mc[0].metric("Runs", sm["n_runs"])
        mc[1].metric("Avg return %", fmt(sm["mean"]["Return [%]"]))
        mc[2].metric("Avg Sharpe", fmt(sm["mean"]["Sharpe Ratio"]))
        mc[3].metric("Avg max drawdown %", fmt(sm["mean"]["Max. Drawdown [%]"]))
        st.caption(f'Best run by return: #{sm["best_by_return"]} · by Sharpe: #{sm["best_by_sharpe"]} · '
                   f'worst by return: #{sm["worst_by_return"]}')
        st.dataframe(pd.DataFrame(sm["by_market"]), hide_index=True)
    stab = sm["stability"]
    if stab and stab["share_within_80pct"] is None:
        st.info(f'Latest optimization #{stab["optimization_id"]}: best {stab["maximize"]} is not positive, '
                "so stability wasn't measured.")
    elif stab:
        msg = (f'Latest optimization #{stab["optimization_id"]}: {stab["share_within_80pct"]:.0%} of '
               f'{stab["combinations"]} combinations score within 80% of the best {stab["maximize"]}.')
        if stab["likely_overfit"]:
            st.warning(msg + " The best result is a lone spike, so it is likely overfit.")
        else:
            st.info(msg)

    st.subheader("Claude's analysis")
    runs = db.list_runs(conn, sid)
    label = {r["id"]: f'#{r["id"]} {r["ticker"]} {r["interval"]} {r["start_date"]}->{r["end_date"]}' for r in runs}
    pick = st.multiselect("Runs to include (empty = latest 20)", list(label), format_func=label.get,
                          key=f"ins_runs_{sid}")
    if st.button("Analyze with Claude", type="primary", disabled=not runs or not generate.has_credentials()):
        try:
            with st.spinner("Claude is reviewing the results..."):
                insights.analyze(conn, sid, pick or None)
        except Exception as e:
            st.error(f"Analysis failed: {e}")
    for i, ins in enumerate(db.list_insights(conn, sid)):
        with st.expander(f'{ins["created_at"][:16]} · {len(ins["run_ids"])} runs · {ins["model"]}', expanded=i == 0):
            st.markdown(ins["content"])

    with st.expander("Delete strategy"):
        sure = st.checkbox(f'Yes, delete "{s["name"]}" with all its versions, runs, optimizations and insights',
                           key=f"del_{sid}")
        if st.button("Delete permanently", disabled=not sure):
            db.delete_strategy(conn, sid)
            state.pop("strategy_id", None)
            st.switch_page("ui/library.py")
