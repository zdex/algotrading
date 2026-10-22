"""Panel charts. Every series on this page is simulated."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from market_monitor.model import Holding
from market_monitor.series import (
    breadth,
    commodities,
    credit_spreads,
    crypto_board,
    earnings_board,
    factor_exposures,
    fund_quality,
    fx_matrix,
    growth_inflation,
    liquidity_gauge,
    macro_surprise,
    market_map,
    portfolio_history,
    rate_path,
    regional_scorecard,
    sector_constituents,
    sector_performance,
    stress_tests,
    themes,
    ticker_ribbon,
    volatility_curve,
    yield_curve,
)
from ui.components import theme as t


def _show(fig: go.Figure) -> None:
    fig.update_layout(height=340)
    st.plotly_chart(fig, width="stretch")
    st.caption("Simulated series. Not a live quote.")


def macro_charts() -> None:
    basis = st.radio("Surprise basis", ["YoY", "MoM"], horizontal=True, key="macro-basis")
    frame = macro_surprise()
    column = "yoy" if basis == "YoY" else "mom"
    pivot = frame.pivot(index="country", columns="indicator", values=column)
    heat = go.Figure(go.Heatmap(
        z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
        colorscale=t.DIVERGING, zmid=0, colorbar={"title": basis},
    ))
    heat.update_layout(title=f"Macro surprise vs consensus ({basis})")
    left, right = st.columns(2)
    with left:
        _show(heat)
    with right:
        quad = growth_inflation()
        fig = go.Figure(go.Scatter(
            x=quad["gdp"], y=quad["inflation"], mode="markers+text", text=quad["country"],
            textposition="top center", marker={"size": 14, "color": t.SERIES[0]},
        ))
        fig.update_layout(title="Growth / inflation quadrant", xaxis_title="GDP, simulated %", yaxis_title="Inflation, simulated %")
        _show(fig)
    path = rate_path()
    rates = go.Figure()
    rates.add_trace(go.Scatter(x=path["date"], y=path["policy_rate"], name="Policy rate", mode="lines"))
    rates.add_trace(go.Scatter(x=path["date"], y=path["futures_implied"], name="Futures-implied", mode="lines", line={"dash": "dot"}))
    rates.update_layout(title="Policy rate and futures-implied path", yaxis_title="%")
    curve = yield_curve()
    curve_fig = go.Figure(go.Scatter(x=curve["tenor"], y=curve["yield_pct"], mode="lines+markers", name="Yield"))
    curve_fig.update_layout(title="Simulated sovereign yield curve", yaxis_title="%")
    left, right = st.columns(2)
    with left:
        _show(rates)
    with right:
        _show(curve_fig)
    st.subheader("Regional scorecards")
    st.dataframe(regional_scorecard(), hide_index=True, width="stretch")


def markets_charts() -> None:
    ribbon = ticker_ribbon()
    chips = []
    for row in ribbon.itertuples():
        tone = "good" if row.change_pct >= 0 else "critical"
        chips.append(f":{ 'green' if tone == 'good' else 'red' }-badge[{row.symbol} {row.change_pct:+.1f}%]")
    st.markdown(" ".join(chips))
    st.caption("Ticker ribbon uses the simulated batch. Treat every print as delayed demo data.")
    window = st.radio("Chart window", ["1M", "3M", "1Y"], horizontal=True, key="mkt-window")
    st.caption(f"Window {window} rescales the demo liquidity and breadth paths. It does not load a live history.")
    left, right = st.columns(2)
    world = market_map()
    colors = [t.GOOD if value >= 0 else t.CRITICAL for value in world["change_pct"]]
    world_fig = go.Figure(go.Bar(x=world["market"], y=world["change_pct"], marker_color=colors))
    world_fig.update_layout(title="Global market map, session change", yaxis_title="%")
    with left:
        _show(world_fig)
    liq = liquidity_gauge()
    if window == "1M":
        liq = liq.tail(6)
    elif window == "3M":
        liq = liq.tail(9)
    gauge = go.Figure(go.Scatter(x=liq["date"], y=liq["conditions_index"], mode="lines", fill="tozeroy"))
    gauge.update_layout(title="Financial conditions (higher = easier, simulated)")
    with right:
        _show(gauge)
        st.metric("Latest conditions", f"{liq['conditions_index'].iloc[-1]:.2f}")
    wide = breadth()
    if window == "1M":
        wide = wide.tail(6)
    elif window == "3M":
        wide = wide.tail(9)
    breadth_fig = go.Figure(go.Scatter(x=wide["date"], y=wide["pct_above_200d"], mode="lines", name="% above 200-day"))
    breadth_fig.update_layout(title="Equity breadth", yaxis_title="% of members")
    vol = volatility_curve()
    vol_fig = go.Figure(go.Scatter(x=vol["tenor"], y=vol["implied_vol"], mode="lines+markers"))
    vol_fig.update_layout(title="Volatility curve", yaxis_title="Implied vol")
    left, right = st.columns(2)
    with left:
        _show(breadth_fig)
    with right:
        _show(vol_fig)
    left, right = st.columns(2)
    goods = commodities()
    goods_fig = go.Figure(go.Bar(x=goods["commodity"], y=goods["change_pct"]))
    goods_fig.update_layout(title="Commodity dashboard, session change", yaxis_title="%")
    fx = fx_matrix()
    fx_fig = go.Figure(go.Bar(x=fx["pair"], y=fx["change_pct"]))
    fx_fig.update_layout(title="FX matrix, session change", yaxis_title="%")
    with left:
        _show(goods_fig)
    with right:
        _show(fx_fig)
    st.subheader("Crypto and alternatives")
    st.dataframe(crypto_board(), hide_index=True, width="stretch")
    st.caption("Private-market items in category 18 stay on a slower cadence than these liquid prints.")


def corporate_charts(events) -> None:
    board = earnings_board()
    colors = [t.GOOD if value >= 0 else t.CRITICAL for value in board["surprise_pct"]]
    beat = go.Figure(go.Bar(x=board["symbol"], y=board["surprise_pct"], marker_color=colors))
    beat.update_layout(title="Beat / miss vs consensus, simulated %", yaxis_title="%")
    revisions = go.Figure(go.Bar(x=board["symbol"], y=board["revision"], name="Estimate revision"))
    revisions.update_layout(title="Estimate revision leaderboard", yaxis_title="Index points")
    left, right = st.columns(2)
    with left:
        _show(beat)
    with right:
        _show(revisions)
    st.subheader("Guidance tracker")
    st.dataframe(board[["symbol", "guidance", "surprise_pct", "revision"]], hide_index=True, width="stretch")
    upcoming = [event for event in events if event.category_id == 3 and event.scheduled_at]
    st.subheader("Earnings calendar")
    if upcoming:
        st.dataframe(
            pd.DataFrame([{
                "when": event.scheduled_at, "company": event.title, "type": event.event_type, "timezone": event.timezone,
            } for event in upcoming[:12]]),
            hide_index=True, width="stretch",
        )
    else:
        st.caption("No scheduled earnings in the current filter.")


def risk_charts() -> None:
    spreads = credit_spreads()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spreads["date"], y=spreads["ig_bps"], name="Investment grade"))
    fig.add_trace(go.Scatter(x=spreads["date"], y=spreads["hy_bps"], name="High yield"))
    fig.update_layout(title="Credit spreads", yaxis_title="bps")
    _show(fig)


def sector_charts() -> None:
    frame = sector_performance()
    window = st.radio("Relative window", ["1W", "1M", "3M", "1Y"], horizontal=True, key="sec-window")
    colors = [t.GOOD if value >= 0 else t.CRITICAL for value in frame[window]]
    heat = go.Figure(go.Bar(x=frame["sector"], y=frame[window], marker_color=colors))
    heat.update_layout(title=f"Sector relative performance, {window}", yaxis_title="%")
    _show(heat)
    left, right = st.columns(2)
    rev = go.Figure(go.Bar(x=frame["sector"], y=frame["revision"]))
    rev.update_layout(title="Earnings revision trend", yaxis_title="Simulated revision")
    val = go.Figure(go.Bar(x=frame["sector"], y=frame["valuation_percentile"]))
    val.update_layout(title="Valuation percentile", yaxis_title="Percentile")
    with left:
        _show(rev)
    with right:
        _show(val)
    st.subheader("Structural themes")
    st.dataframe(themes(), hide_index=True, width="stretch")
    constituents = sector_constituents()
    picked = st.selectbox("Inspect a sector", list(constituents), key="sec-names")
    names = constituents[picked]
    if names:
        st.write("Demo constituents: " + ", ".join(names))
    else:
        st.caption("No demo constituent is mapped to this sector. The sector row is still in the catalog.")


def portfolio_charts(holdings: list[Holding], book_choice: str) -> None:
    if not holdings:
        st.warning("Holdings are unavailable. Connect a book, enter holdings, or switch to the demo book.")
        return
    frame = pd.DataFrame([row.__dict__ for row in holdings])
    tree = go.Figure(go.Treemap(
        labels=frame["symbol"] + " " + frame["sector"],
        parents=[""] * len(frame),
        values=frame["market_value"].clip(lower=0),
        textinfo="label+percent root",
    ))
    tree.update_layout(title="Allocation")
    _show(tree)
    by_sector = frame.groupby("sector", as_index=False)["weight_pct"].sum()
    by_country = frame.groupby("country", as_index=False)["weight_pct"].sum()
    left, right = st.columns(2)
    with left:
        fig = go.Figure(go.Bar(x=by_sector["sector"], y=by_sector["weight_pct"]))
        fig.update_layout(title="Sector weights", yaxis_title="%")
        _show(fig)
    with right:
        fig = go.Figure(go.Bar(x=by_country["country"], y=by_country["weight_pct"]))
        fig.update_layout(title="Country weights", yaxis_title="%")
        _show(fig)
    if book_choice == "demo":
        history = portfolio_history()
        lines = go.Figure()
        lines.add_trace(go.Scatter(x=history["date"], y=history["portfolio"], name="Demo book"))
        lines.add_trace(go.Scatter(x=history["date"], y=history["benchmark"], name="Simulated benchmark", line={"dash": "dot"}))
        lines.update_layout(title="Demo book vs a simulated benchmark")
        _show(lines)
        dd = go.Figure()
        dd.add_trace(go.Scatter(x=history["date"], y=history["drawdown_pct"], name="Drawdown %"))
        dd.add_trace(go.Scatter(x=history["date"], y=history["vol_pct"], name="Rolling vol %"))
        dd.update_layout(title="Rolling volatility and drawdown")
        _show(dd)
        perf = sector_performance().set_index("sector")["1M"]
        rows = []
        for holding in holdings:
            sector_move = float(perf[holding.sector]) if holding.sector in perf.index else 0.0
            rows.append({
                "symbol": holding.symbol,
                "weight_pct": holding.weight_pct,
                "sector_1m_pct": sector_move,
                "contribution_pct": round(holding.weight_pct / 100 * sector_move, 3),
            })
        st.subheader("Illustrative attribution")
        st.caption("Weight times that sector's simulated 1-month move. Not a Brinson attribution.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("The equity, drawdown, and attribution charts are tied to the simulated demo book. They are hidden for the paper and manual books so they are not mistaken for that book.")
    left, right = st.columns(2)
    factors = factor_exposures()
    factor_fig = go.Figure(go.Bar(x=factors["factor"], y=factors["exposure"]))
    factor_fig.update_layout(title="Factor exposure, demo model")
    with left:
        _show(factor_fig)
    with right:
        st.subheader("Fund quality")
        st.dataframe(fund_quality(), hide_index=True, width="stretch")
        st.caption("Premium, expense ratio, and tracking error are simulated fund-file fields.")
    st.subheader("Scenario stress")
    st.dataframe(stress_tests(), hide_index=True, width="stretch")
    st.caption("Stress results are a fixed demo grid. VaR and expected shortfall elsewhere in the catalog carry the same limitation: they are model output, not a guarantee.")
    top = frame.sort_values("weight_pct", ascending=False).head(5)
    st.subheader("Concentration")
    st.dataframe(top[["symbol", "name", "weight_pct", "sector", "country"]], hide_index=True, width="stretch")
