"""Risk: exposure vs limits, correlation of holdings, sizing breakdown, rejection log."""

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.components import charts, state, widgets
from ui.components import theme as t

st.title("Risk")

runs = state.list_runs(state.results_dir())
if runs.empty:
    state.no_runs_message()
    st.stop()

run_id = state.run_picker()
r = state.load_run(state.results_dir(), run_id)
rk = r.config.risk
eq = r.equity

halted = r.meta.get("halted")
st.markdown("  ".join([
    widgets.pill("Drawdown halt", "TRIGGERED" if halted else "not triggered", "critical" if halted else "good"),
    widgets.pill("Max drawdown", t.pct(r.metrics.get("max_drawdown_pct"), already_pct=True), "neutral"),
    widgets.pill("Halt level", f"{rk.max_drawdown_pct:.0%} from {'peak' if rk.drawdown_from_peak else 'start'}",
                 "neutral"),
    widgets.pill("Sizing", (f"vol target {rk.target_annual_vol:.0%} ({rk.vol_target_mode})"
                            if rk.use_vol_targeting else "fixed %"), "neutral"),
]))

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(charts.sector_exposure(r.sector_exposure, rk.max_sector_pct, "Sector exposure (end of run)"),
                    width="stretch")
with c2:
    if not eq.empty:
        st.plotly_chart(charts.line(eq["gross_exposure"], "Gross exposure", ".0%",
                                    hline=rk.max_gross_exposure, hline_label="cap"), width="stretch")
        st.plotly_chart(charts.line(eq["open_positions"].astype(float), "Open positions", ",.0f",
                                    hline=rk.max_open_positions, hline_label="limit", height=200),
                        width="stretch")

# ── Sizing breakdown ─────────────────────────────────────────
st.subheader("Position sizing at end of run")
pos = r.positions
if pos.empty:
    st.caption("No open positions.")
else:
    st.caption(
        "Target weight is what the vol-targeting formula asks for (capped at "
        f"{rk.max_position_pct:.0%}); actual weight has drifted with price since entry."
    )
    df = pos[["symbol", "sector", "annual_vol", "target_weight", "weight"]].copy()
    for c in ["annual_vol", "target_weight", "weight"]:
        df[c] = df[c] * 100
    df["capped"] = df["target_weight"] >= rk.max_position_pct * 100 - 1e-6
    st.dataframe(df, hide_index=True, width="stretch", height=300, column_config={
        "symbol": "Symbol", "sector": "Sector",
        "annual_vol": st.column_config.NumberColumn("Annual vol", format="%.1f%%"),
        "target_weight": st.column_config.NumberColumn("Target weight", format="%.2f%%"),
        "weight": st.column_config.NumberColumn("Actual weight", format="%.2f%%"),
        "capped": st.column_config.CheckboxColumn("At cap"),
    })
    capped = int(df["capped"].sum())
    st.caption(f"{capped} of {len(df)} positions are sized at the {rk.max_position_pct:.0%} cap.")

# ── Correlation of holdings ──────────────────────────────────
if not pos.empty and len(pos) > 1:
    end = r.config.end_date
    run_cache = r.config.cache_dir if os.path.isdir(r.config.cache_dir) else state.cache_dir()
    px = state.closes(run_cache, tuple(pos["symbol"]), None, end)
    if not px.empty:
        rets = px.tail(rk.corr_lookback + 1).pct_change(fill_method=None).dropna(how="all")
        corr = rets.corr()
        order = pos["symbol"][pos["symbol"].isin(corr.columns)].tolist()
        corr = corr.loc[order, order]
        st.plotly_chart(charts.correlation_heatmap(
            corr, f"Correlation of holdings (last {rk.corr_lookback} days, filter at {rk.max_correlation:.2f})"),
            width="stretch")

# ── Rejections ───────────────────────────────────────────────
st.subheader("Signals blocked by risk")
rej = r.rejections
if rej.empty:
    st.caption("None.")
else:
    rej = rej.copy()
    rej["reason"] = rej["check"].map(lambda c: widgets.CHECK_LABELS.get(c, c))
    rej["month"] = pd.to_datetime(rej["timestamp"]).dt.to_period("M").dt.to_timestamp()
    monthly = rej.groupby(["month", "reason"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for i, col in enumerate(monthly.columns):
        fig.add_trace(go.Bar(x=monthly.index, y=monthly[col], name=col,
                             marker=dict(color=t.SERIES[i % len(t.SERIES)], line=dict(color=t.SURFACE, width=1)),
                             hovertemplate=f"{col}: %{{y}}<extra></extra>"))
    fig.update_layout(barmode="stack", title="Blocked signals per month", height=280, bargap=0.25)
    st.plotly_chart(fig, width="stretch")
    widgets.decisions_table(rej, height=340)
