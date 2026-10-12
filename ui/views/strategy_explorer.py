"""Strategy Explorer: see the MA crossover signals on one symbol and how sensitive they are."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from strategy.examples.ma_crossover_vectorised import MACrossoverConfig, VectorisedMACrossover
from ui.components import charts, state
from ui.components import theme as t

st.title("Strategy Explorer")
st.caption("MA crossover on a single symbol. Markers show where the backtest would fill: "
           "the open of the bar after the signal.")

cache = state.cache_dir()
cov = state.coverage(cache)
if cov.empty:
    st.info("The price cache is empty. Download data from Universe & Data first.", icon=":material/info:")
    st.stop()

symbols = sorted(cov.loc[cov["cached"], "symbol"])
c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
symbol = c1.selectbox("Symbol", symbols, index=symbols.index("AAPL") if "AAPL" in symbols else 0)
fast = c2.number_input("Fast MA", 2, 200, 10)
slow = c3.number_input("Slow MA", 3, 400, 30)
df_all = state.ohlcv(cache, symbol)
if df_all is None or df_all.empty:
    st.warning(f"No data for {symbol}.")
    st.stop()
lo, hi = df_all.index.min().date(), df_all.index.max().date()
default_start = max(lo, (df_all.index.max() - pd.Timedelta(days=365)).date())
period = c4.slider("Period", min_value=lo, max_value=hi, value=(default_start, hi))

if fast >= slow:
    st.error("Fast MA must be shorter than slow MA.")
    st.stop()

model = VectorisedMACrossover(MACrossoverConfig(fast_period=int(fast), slow_period=int(slow)))
close = df_all[["close"]].rename(columns={"close": symbol})
signals = model.generate(close)[symbol]
fast_ma = close[symbol].rolling(int(fast)).mean()
slow_ma = close[symbol].rolling(int(slow)).mean()

# Position after each bar's close; trades fill at the next bar's open
state_ = signals.replace("", "FLAT")
held = (state_ == "LONG").astype(int)
change = held.diff().fillna(held)
nxt_open = df_all["open"].shift(-1)
nxt_date = pd.Series(df_all.index, index=df_all.index).shift(-1)
entries = pd.DataFrame({"price": nxt_open[change > 0].values}, index=nxt_date[change > 0].values).dropna()
exits = pd.DataFrame({"price": nxt_open[change < 0].values}, index=nxt_date[change < 0].values).dropna()

start, end = pd.Timestamp(period[0]), pd.Timestamp(period[1])
win = (df_all.index >= start) & (df_all.index <= end)
in_range = lambda x: x[(x.index >= start) & (x.index <= end)]  # noqa: E731

st.plotly_chart(charts.candles_with_signals(
    df_all[win], in_range(fast_ma), in_range(slow_ma), in_range(entries), in_range(exits),
    f"{symbol} · MA {fast}/{slow}"), width="stretch")

# ── Signal vs buy & hold over the selected period ────────────
open_ret = df_all["open"].pct_change().shift(-1)          # return from today's open to tomorrow's open
pos_at_open = held.shift(1).fillna(0)                      # yesterday's signal → position at today's open
strat = (1 + (pos_at_open * open_ret).fillna(0))[win].cumprod()
bh = (1 + open_ret.fillna(0))[win].cumprod()

fig = go.Figure()
fig.add_trace(go.Scatter(x=bh.index, y=bh.values, name="Buy & hold", mode="lines",
                         line=dict(width=2, color=t.BENCH_1), hovertemplate="%{y:.3f}"))
fig.add_trace(go.Scatter(x=strat.index, y=strat.values, name="MA signal (long/flat)", mode="lines",
                         line=dict(width=2.5, color=t.STRATEGY), hovertemplate="%{y:.3f}"))
fig.update_layout(title="Growth of $1 (before costs)", height=300, yaxis_tickformat=".2f")
st.plotly_chart(fig, width="stretch")

c1, c2, c3, c4 = st.columns(4)
n_trades = int(((change > 0) & win).sum())
c1.metric("Entries in period", n_trades, border=True)
c2.metric("Time in market", t.pct(float(held[win].mean())), border=True)
c3.metric("Signal return", t.pct(float(strat.iloc[-1] - 1)) if len(strat) else "—", border=True)
c4.metric("Buy & hold return", t.pct(float(bh.iloc[-1] - 1)) if len(bh) else "—", border=True)

# ── Parameter sensitivity ────────────────────────────────────
with st.expander("Parameter sensitivity (signal return over the period, before costs)"):
    fasts = [5, 10, 15, 20, 30]
    slows = [20, 30, 50, 100, 200]
    grid = pd.DataFrame(index=fasts, columns=slows, dtype=float)
    for f in fasts:
        for s in slows:
            if f >= s:
                continue
            sig = VectorisedMACrossover(MACrossoverConfig(f, s)).generate(close)[symbol]
            h = (sig == "LONG").astype(int).shift(1).fillna(0)
            grid.loc[f, s] = float((1 + (h * open_ret).fillna(0))[win].prod() - 1)
    lim = float(grid.abs().max().max() or 0.01)
    fig = go.Figure(go.Heatmap(
        z=grid.values, x=[f"slow {s}" for s in slows], y=[f"fast {f}" for f in fasts],
        colorscale=t.DIVERGING, zmin=-lim, zmax=lim, xgap=2, ygap=2,
        text=[["" if pd.isna(v) else f"{v:.1%}" for v in row] for row in grid.values],
        texttemplate="%{text}", hovertemplate="%{y}, %{x}: %{z:.1%}<extra></extra>", showscale=False,
    ))
    fig.update_layout(height=280, hovermode="closest", yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")

st.caption("The RSI mean-reversion strategy isn't in the uploaded files, so only MA crossover is shown here.")
