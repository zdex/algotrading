"""Backtest Results: full report for one run, plus side-by-side comparison of runs."""


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backtester.metrics import monthly_returns
from backtester.results_store import delete_run
from ui.components import charts, state, widgets
from ui.components import theme as t

st.title("Backtest Results")

runs = state.list_runs(state.results_dir())
if runs.empty:
    state.no_runs_message()
    st.stop()

tab_run, tab_compare = st.tabs(["Single run", "Compare runs"])

with tab_run:
    run_id = state.run_picker()
    r = state.load_run(state.results_dir(), run_id)
    m = r.metrics
    for w in r.meta.get("warnings", []):
        st.warning(w, icon=":material/warning:")

    widgets.kpi_row(m, widgets.STANDARD_KPIS)
    widgets.kpi_row(m, [
        ("annual_vol_pct", "Volatility", "pct"),
        ("sortino", "Sortino", "ratio"),
        ("calmar", "Calmar", "ratio"),
        ("profit_factor", "Profit factor", "ratio"),
        ("beta", "Beta", "ratio"),
        ("alpha_annual_pct", "Alpha (annual)", "pct"),
    ])

    overview, trades_tab, signals_tab, positions_tab, config_tab = st.tabs(
        ["Performance", "Trades", "Signals & risk", "Positions", "Config & log"])

    with overview:
        if r.equity.empty:
            st.caption("No equity data.")
        else:
            eq = r.equity["equity"]
            st.plotly_chart(charts.equity_vs_benchmarks(eq, r.benchmarks, "Equity vs benchmarks"),
                            width="stretch")
            st.plotly_chart(charts.drawdown(r.equity["drawdown"]), width="stretch")
            c1, c2 = st.columns(2)
            c1.plotly_chart(charts.line(r.equity["gross_exposure"], "Gross exposure", ".0%",
                                        hline=r.config.risk.max_gross_exposure, hline_label="cap"),
                            width="stretch")
            c2.plotly_chart(charts.line(r.equity["open_positions"].astype(float), "Open positions", ",.0f",
                                        hline=r.config.risk.max_open_positions, hline_label="limit"),
                            width="stretch")
            rolling = eq.pct_change().rolling(126).apply(
                lambda x: x.mean() / x.std() * (252 ** 0.5) if x.std() > 0 else float("nan"), raw=True)
            st.plotly_chart(charts.line(rolling.dropna().rename("Sharpe"), "Rolling 6-month Sharpe", ".2f",
                                        hline=0.0), width="stretch")
            st.plotly_chart(charts.monthly_heatmap(monthly_returns(eq.iloc[1:] if len(eq) > 2 else eq)),
                            width="stretch")

    with trades_tab:
        tr = r.trades
        if tr.empty:
            st.caption("No closed trades.")
        else:
            c1, c2, c3 = st.columns(3)
            syms = c1.multiselect("Symbols", sorted(tr["symbol"].unique()))
            outcome = c2.segmented_control("Outcome", ["All", "Winners", "Losers"], default="All")
            view = tr if not syms else tr[tr["symbol"].isin(syms)]
            if outcome == "Winners":
                view = view[view["net_pnl"] > 0]
            elif outcome == "Losers":
                view = view[view["net_pnl"] <= 0]
            c3.metric("Net P&L of selection", t.money(view["net_pnl"].sum()), border=True)
            widgets.trades_table(view, height=420)
            st.download_button("Download trades CSV", tr.to_csv(index=False), f"{run_id}-trades.csv",
                               icon=":material/download:")

            by_symbol = tr.groupby("symbol")["net_pnl"].sum().sort_values()
            top = pd.concat([by_symbol.head(10), by_symbol.tail(10)]).drop_duplicates()
            fig = go.Figure(go.Bar(
                x=top.values, y=top.index, orientation="h",
                marker=dict(color=[t.STRATEGY if v >= 0 else t.CRITICAL for v in top.values], cornerradius=4),
                hovertemplate="%{y}: %{x:$,.0f}<extra></extra>",
            ))
            fig.update_layout(title="Biggest contributors and detractors (net P&L)",
                              height=40 + 24 * len(top), hovermode="closest", showlegend=False,
                              xaxis_tickformat="$,.0s")
            st.plotly_chart(fig, width="stretch")

    with signals_tab:
        dec = r.decisions
        if dec.empty:
            st.caption("No signals.")
        else:
            c1, c2 = st.columns(2)
            actions = c1.multiselect("Outcome", sorted(dec["action"].unique()),
                                     default=[a for a in ["approved", "rejected", "reversed"]
                                              if a in dec["action"].unique()])
            sym = c2.text_input("Symbol filter")
            view = dec[dec["action"].isin(actions)] if actions else dec
            if sym:
                view = view[view["symbol"].str.contains(sym.strip().upper())]
            counts = dec["action"].value_counts()
            st.markdown("  ".join(f":gray-badge[{k}: {v}]" for k, v in counts.items()))
            widgets.decisions_table(view, height=460)
            st.download_button("Download decisions CSV", dec.to_csv(index=False), f"{run_id}-decisions.csv",
                               icon=":material/download:")

    with positions_tab:
        widgets.positions_table(r.positions, height=480)

    with config_tab:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Configuration**")
            st.json(r.config.to_dict(), expanded=1)
        with c2:
            st.markdown("**Run info**")
            info = {k: v for k, v in r.meta.items() if k not in ("log_warnings", "warnings")}
            st.json(info, expanded=1)
            logs = r.meta.get("log_warnings", [])
            st.markdown(f"**Log warnings** ({len(logs)})")
            st.code("\n".join(logs) or "none", language=None)
        if not r.liquidity_rejections.empty:
            st.markdown(f"**Excluded by liquidity filter** ({len(r.liquidity_rejections)})")
            st.dataframe(r.liquidity_rejections, hide_index=True, width="stretch", height=240)
        with st.popover("Delete this run", icon=":material/delete:"):
            st.write(f"Delete `{run_id}` from results/? This can't be undone.")
            if st.button("Delete", type="primary"):
                delete_run(run_id, state.results_dir())
                state.list_runs.clear()
                st.session_state.pop("selected_run", None)
                st.rerun()

with tab_compare:
    ids = runs["run_id"].tolist()
    chosen = st.multiselect("Runs to compare", ids, default=ids[:min(3, len(ids))], max_selections=8)
    if chosen:
        fig = go.Figure()
        rows = []
        for i, rid in enumerate(chosen):
            rr = state.load_run(state.results_dir(), rid)
            if not rr.equity.empty:
                eq = rr.equity["equity"] / rr.equity["equity"].iloc[0]
                fig.add_trace(go.Scatter(x=eq.index, y=eq.values, name=rid, mode="lines",
                                         line=dict(width=2, color=t.SERIES[i % len(t.SERIES)]),
                                         hovertemplate="%{y:.3f}"))
            c = rr.config
            rows.append({
                "run": rid,
                "period": f"{c.start_date} → {c.end_date}",
                "MA": f"{c.strategy.fast_period}/{c.strategy.slow_period}",
                "vol mode": c.risk.vol_target_mode if c.risk.use_vol_targeting else "off",
                "max pos": c.risk.max_open_positions,
                "slippage bps": c.sim.slippage_bps,
                **{k: rr.metrics.get(k) for k in
                   ["total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct", "win_rate_pct", "num_trades"]},
            })
        fig.update_layout(title="Equity, indexed to 1.0", height=380, yaxis_tickformat=".2f")
        st.plotly_chart(fig, width="stretch")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
