"""Command Center: system status, latest results, positions, risk and signals at a glance."""

import pandas as pd
import streamlit as st

from ui.components import charts, state, widgets
from ui.components import theme as t

st.title("Command Center")

cache = state.cache_dir()
runs = state.list_runs(state.results_dir())
cov = state.coverage(cache)

# ── 1. System status ─────────────────────────────────────────
pills = [widgets.pill("Mode", "PAPER", "good"),
         widgets.pill("Live trading", "not connected", "neutral")]
if cov.empty:
    pills.append(widgets.pill("Data cache", "empty", "critical"))
else:
    last = pd.to_datetime(cov["last_date"]).max()
    age = (pd.Timestamp.now().normalize() - last).days
    pills.append(widgets.pill("Data", f"{cov['cached'].sum()} symbols to {last.date()}",
                              "good" if age <= 5 else "warning"))
pills.append(widgets.pill("Saved runs", str(len(runs)), "good" if len(runs) else "warning"))
st.markdown("  ".join(pills))

if runs.empty:
    state.no_runs_message()
    st.stop()

run_id = state.run_picker("Showing backtest")
r = state.load_run(state.results_dir(), run_id)
m = r.metrics

for w in r.meta.get("warnings", []):
    st.warning(w, icon=":material/warning:")

# ── 2. KPIs ──────────────────────────────────────────────────
widgets.kpi_row(m, [
    ("final_equity", "Equity", "money"),
    ("total_return_pct", "Total return", "pct"),
    ("cagr_pct", "CAGR", "pct"),
    ("sharpe", "Sharpe", "ratio"),
    ("max_drawdown_pct", "Max drawdown", "pct"),
    ("benchmark_return_pct", f"{(r.config.benchmarks or ['Benchmark'])[0]} return", "pct"),
])

# ── 3. Equity vs benchmarks, drawdown ────────────────────────
if not r.equity.empty:
    st.plotly_chart(charts.equity_vs_benchmarks(r.equity["equity"], r.benchmarks,
                                                title=f"Equity vs benchmarks ({m.get('start')} → {m.get('end')})"),
                    width="stretch")
    st.plotly_chart(charts.drawdown(r.equity["drawdown"]), width="stretch")

# ── 4. Positions and sector exposure ─────────────────────────
left, right = st.columns([3, 2])
with left:
    st.subheader("Open positions at end of run")
    st.caption(f"{len(r.positions)} positions · gross exposure "
               f"{t.pct(r.equity['gross_exposure'].iloc[-1]) if not r.equity.empty else '—'}")
    widgets.positions_table(r.positions, height=360, limit=15)
with right:
    st.plotly_chart(charts.sector_exposure(r.sector_exposure, r.config.risk.max_sector_pct,
                                           title="Sector exposure vs cap"), width="stretch")

# ── 5. Latest signals and what risk did with them ────────────
left, right = st.columns([3, 2])
d = r.decisions
with left:
    st.subheader("Latest signals")
    if d.empty:
        st.caption("No signals.")
    else:
        d = d.copy()
        d["date"] = pd.to_datetime(d["timestamp"]).dt.normalize()
        last_date = d["date"].max()
        st.caption(f"Signal day {last_date.date()}. Orders fill at the next bar's open.")
        widgets.decisions_table(d[d["date"] == last_date], height=260)
with right:
    rej = r.rejections
    if rej.empty:
        st.subheader("Risk rejections")
        st.caption("No signals were blocked by the risk manager.")
    else:
        counts = rej["check"].map(lambda c: widgets.CHECK_LABELS.get(c, c)).value_counts()
        st.plotly_chart(charts.counts_bar(counts, f"Signals blocked by risk ({len(rej)})"),
                        width="stretch")

# ── 6. Recent trades ─────────────────────────────────────────
st.subheader("Recent closed trades")
widgets.trades_table(r.trades.sort_values("exit_time").tail(15) if not r.trades.empty else r.trades,
                     height=300)

# ── 7. Phase 1 verdict ───────────────────────────────────────
with st.container(border=True):
    st.markdown("**Phase 1 verdict (PROCEED / REFINE)**")
    st.caption("Not wired up yet: run_phase1.py wasn't in the uploaded files. "
               "See the Phase 1 Validation page.")
