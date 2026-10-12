"""Backtest Lab: configure and run the large-universe backtest, save the result."""

from datetime import date

import streamlit as st

from backtester.runner import STEPS, BacktestConfig, run_backtest
from backtester.results_store import save_result
from core.risk_large import LargeUniverseRiskConfig
from data.filters import FilterConfig
from execution.adapters.simulated import SimConfig
from strategy.examples.ma_crossover_vectorised import MACrossoverConfig
from ui.components import state, widgets

st.title("Backtest Lab")
st.caption("MA crossover over the index universe, with next-open fills and point-in-time risk checks. "
           "Each run is saved to `results/` and shows up on every other page.")

d = BacktestConfig()      # defaults = the values in run_backtest_large.py
cache = state.cache_dir()
sample = cache.endswith("sample_cache")

with st.form("backtest"):
    st.subheader("Run")
    c1, c2, c3, c4 = st.columns(4)
    name = c1.text_input("Run name", value="ma-10-30")
    start = c2.date_input("Start", value=date.fromisoformat(d.start_date))
    end = c3.date_input("End", value=date.fromisoformat(d.end_date))
    cash = c4.number_input("Initial cash ($)", value=d.initial_cash, step=100_000.0, format="%.0f")

    c1, c2 = st.columns([3, 1])
    with c1:
        source = st.radio("Universe", ["Index constituents", "Custom symbols"], horizontal=True)
        i1, i2, i3 = st.columns(3)
        sp = i1.checkbox("S&P 500", value=True)
        nq = i2.checkbox("NASDAQ-100", value=True)
        dj = i3.checkbox("Dow 30", value=True)
        custom = st.text_input("Custom symbols (comma separated, used when 'Custom symbols' is picked)",
                               placeholder="AAPL, MSFT, NVDA")
    with c2:
        offline = st.toggle("Use cached data only", value=sample,
                            help="Skip Yahoo/Wikipedia downloads. Required for the sample data.")
        bench = st.text_input("Benchmarks", value=", ".join(d.benchmarks))

    st.subheader("Strategy · MA crossover")
    c1, c2, c3 = st.columns(3)
    fast = c1.number_input("Fast MA", 2, 200, d.strategy.fast_period)
    slow = c2.number_input("Slow MA", 3, 400, d.strategy.slow_period)
    allow_short = c3.toggle("Allow shorts", value=d.strategy.allow_short)

    st.subheader("Liquidity filter (applied as of the start date)")
    c1, c2, c3 = st.columns(3)
    adv = c1.number_input("Min ADV ($)", value=float(d.filter.min_adv_usd), step=1_000_000.0, format="%.0f")
    min_price = c2.number_input("Min price ($)", value=float(d.filter.min_price), step=1.0)
    min_hist = c3.number_input("Min history (days)", 20, 2000, d.filter.min_history_days)

    st.subheader("Risk")
    rk = d.risk
    c1, c2, c3, c4 = st.columns(4)
    max_pos = c1.number_input("Max position (% equity)", 0.1, 100.0, rk.max_position_pct * 100, step=0.5)
    default_order = c2.number_input("Default order (% equity)", 0.1, 100.0, rk.default_order_pct * 100, step=0.5)
    max_open = c3.number_input("Max open positions", 1, 1000, rk.max_open_positions)
    max_gross = c4.number_input("Max gross exposure (%)", 10.0, 300.0, rk.max_gross_exposure * 100, step=10.0)
    c1, c2, c3, c4 = st.columns(4)
    max_sector = c1.number_input("Max sector (% equity)", 1.0, 100.0, rk.max_sector_pct * 100, step=1.0)
    max_corr = c2.number_input("Max correlation", 0.0, 1.0, float(rk.max_correlation), step=0.05)
    max_dd = c3.number_input("Drawdown halt (%)", 1.0, 100.0, rk.max_drawdown_pct * 100, step=1.0)
    dd_peak = c4.toggle("Drawdown from peak", value=rk.drawdown_from_peak,
                        help="Off = measure loss from starting cash (the original behaviour).")
    c1, c2, c3 = st.columns(3)
    use_vol = c1.toggle("Volatility targeting", value=rk.use_vol_targeting)
    target_vol = c2.number_input("Target annual vol (%)", 1.0, 100.0, rk.target_annual_vol * 100, step=1.0)
    vol_mode = c3.selectbox(
        "Vol target applies to", ["portfolio", "per_position"],
        index=["portfolio", "per_position"].index(rk.vol_target_mode),
        format_func={"portfolio": "Whole portfolio (split across slots)",
                     "per_position": "Each position (original — cap almost always binds)"}.get,
    )

    st.subheader("Costs")
    c1, c2 = st.columns(2)
    slip = c1.number_input("Slippage (bps)", 0.0, 100.0, float(d.sim.slippage_bps), step=1.0)
    comm = c2.number_input("Commission per trade ($)", 0.0, 50.0, float(d.sim.commission_per_trade), step=0.5)

    submitted = st.form_submit_button("Run backtest", type="primary", icon=":material/play_arrow:")

if not submitted:
    st.stop()

if fast >= slow:
    st.error("Fast MA must be shorter than slow MA.")
    st.stop()
if start >= end:
    st.error("Start must be before end.")
    st.stop()

cfg = BacktestConfig(
    name=name, start_date=str(start), end_date=str(end), initial_cash=float(cash), cache_dir=cache,
    include_sp500=sp, include_nasdaq=nq, include_dow=dj,
    symbols=[s for s in custom.replace(";", ",").split(",") if s.strip()] if source == "Custom symbols" else None,
    download=not offline,
    benchmarks=[b.strip().upper() for b in bench.split(",") if b.strip()],
    filter=FilterConfig(min_adv_usd=adv, min_price=min_price, min_history_days=int(min_hist)),
    strategy=MACrossoverConfig(fast_period=int(fast), slow_period=int(slow), allow_short=allow_short),
    sim=SimConfig(slippage_bps=slip, commission_per_trade=comm),
    risk=LargeUniverseRiskConfig(
        max_position_pct=max_pos / 100, default_order_pct=default_order / 100,
        max_open_positions=int(max_open), max_gross_exposure=max_gross / 100,
        max_drawdown_pct=max_dd / 100, drawdown_from_peak=dd_peak,
        max_sector_pct=max_sector / 100, max_correlation=max_corr,
        use_vol_targeting=use_vol, target_annual_vol=target_vol / 100, vol_target_mode=vol_mode,
    ),
)

with st.status("Running backtest…", expanded=True) as status:
    step_text = st.empty()
    bar = st.progress(0.0)

    def progress(i: int, msg: str, frac: float) -> None:
        step_text.markdown(f"**Step {i + 1}/{len(STEPS)} · {STEPS[i]}** — {msg}")
        bar.progress(min(1.0, (i + frac) / len(STEPS)))

    try:
        result = run_backtest(cfg, progress)
    except SystemExit as e:
        status.update(label="Backtest stopped", state="error")
        st.error(str(e))
        st.stop()
    run_id = save_result(result, state.results_dir())
    status.update(label=f"Done in {result.meta['elapsed_sec']:.0f}s · saved as {run_id}", state="complete",
                  expanded=False)

state.list_runs.clear()
st.session_state.selected_run = run_id
for w in result.meta["warnings"]:
    st.warning(w, icon=":material/warning:")
widgets.kpi_row(result.metrics, widgets.STANDARD_KPIS)
st.caption(f"{result.meta['tradeable_size']} of {result.meta['universe_size']} symbols tradeable · "
           f"{len(result.rejections)} signals blocked by risk")
st.page_link("views/results.py", label="Open full results", icon=":material/query_stats:")
