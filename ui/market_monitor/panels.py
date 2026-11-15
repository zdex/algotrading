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
    macro_chart_kinds,
    macro_surprise,
    panel_chart_kinds,
    market_map,
    portfolio_history,
    rate_path,
    regional_scorecard,
    sector_constituents,
    sector_performance,
    stress_tests,
    subset_by_geography,
    subset_by_time,
    themes,
    ticker_ribbon,
    volatility_curve,
    yield_curve,
)
from ui.components import theme as t


def _show(fig: go.Figure, note: str = "Simulated series. Not a live quote.") -> None:
    fig.update_layout(height=340)
    st.plotly_chart(fig, width="stretch")
    st.caption(note)


def _missing_series(geography: str | None) -> None:
    if geography:
        st.info(f"No simulated series for {geography}. The event list still uses this filter.")
    else:
        st.info("No simulated series for the current filters.")


def macro_charts(filters: dict) -> None:
    geography = filters.get("geography")
    category_id = filters.get("category_id")
    kinds = macro_chart_kinds(category_id)
    note = f"Simulated series for {geography}." if geography else "Simulated series. Not a live quote."
    if not kinds:
        st.info("This category has no separate chart. The event list below is filtered.")
        return
    if "surprise" in kinds or "quadrant" in kinds:
        _surprise_and_quadrant(geography, kinds, note)
    if "rates" in kinds or "curve" in kinds:
        window_from = filters.get("time_from")
        window_to = filters.get("time_to") if window_from is not None else None
        _rates_and_curve(geography, window_from, window_to, kinds, note)
    if "scorecard" in kinds:
        st.subheader("Regional scorecards")
        card = subset_by_geography(regional_scorecard(), "region", geography)
        if card.empty:
            _missing_series(geography)
        else:
            st.dataframe(card, hide_index=True, width="stretch")
            st.caption(note)


def _surprise_and_quadrant(geography: str | None, kinds: frozenset[str], note: str) -> None:
    slots = st.columns(2) if {"surprise", "quadrant"} <= kinds else (st.container(),)
    slot = 0
    if "surprise" in kinds:
        with slots[slot]:
            slot += 1
            basis = st.radio("Surprise basis", ["YoY", "MoM"], horizontal=True, key="macro-basis")
            frame = subset_by_geography(macro_surprise(), "country", geography)
            column = "yoy" if basis == "YoY" else "mom"
            if frame.empty:
                _missing_series(geography)
            elif frame["country"].nunique() == 1:
                country = frame["country"].iloc[0]
                colors = [t.GOOD if value >= 0 else t.CRITICAL for value in frame[column]]
                fig = go.Figure(go.Bar(x=frame["indicator"], y=frame[column], marker_color=colors))
                fig.update_layout(title=f"{country} surprise vs consensus ({basis})", yaxis_title=basis)
                _show(fig, note)
            else:
                pivot = frame.pivot(index="country", columns="indicator", values=column)
                heat = go.Figure(go.Heatmap(
                    z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
                    colorscale=t.DIVERGING, zmid=0, colorbar={"title": basis},
                ))
                heat.update_layout(title=f"Macro surprise vs consensus ({basis})")
                _show(heat, note)
    if "quadrant" in kinds:
        with slots[slot]:
            full = growth_inflation()
            quad = subset_by_geography(full, "country", geography)
            if quad.empty:
                _missing_series(geography)
            else:
                fig = go.Figure(go.Scatter(
                    x=quad["gdp"], y=quad["inflation"], mode="markers+text", text=quad["country"],
                    textposition="top center", marker={"size": 14, "color": t.SERIES[0]},
                ))
                fig.update_layout(
                    title="Growth / inflation quadrant",
                    xaxis_title="GDP, simulated %",
                    yaxis_title="Inflation, simulated %",
                )
                fig.update_xaxes(range=[float(full["gdp"].min()) - 0.6, float(full["gdp"].max()) + 0.6])
                fig.update_yaxes(range=[float(full["inflation"].min()) - 0.5, float(full["inflation"].max()) + 0.5])
                _show(fig, note)


def _rates_and_curve(geography: str | None, time_from, time_to, kinds: frozenset[str], note: str) -> None:
    slots = st.columns(2) if {"rates", "curve"} <= kinds else (st.container(),)
    slot = 0
    if "rates" in kinds:
        with slots[slot]:
            slot += 1
            path = subset_by_geography(rate_path(), "country", geography)
            if time_from is not None or time_to is not None:
                path = subset_by_time(path, time_from, time_to)
            if path.empty:
                _missing_series(geography)
            else:
                rates = go.Figure()
                if path["country"].nunique() == 1:
                    rates.add_trace(go.Scatter(x=path["date"], y=path["policy_rate"], name="Policy rate", mode="lines"))
                    rates.add_trace(go.Scatter(
                        x=path["date"], y=path["futures_implied"], name="Futures-implied",
                        mode="lines", line={"dash": "dot"},
                    ))
                    title = f"{path['country'].iloc[0]} policy rate and futures-implied path"
                else:
                    for country, group in path.groupby("country", sort=False):
                        rates.add_trace(go.Scatter(x=group["date"], y=group["policy_rate"], name=str(country), mode="lines"))
                    title = "Policy rate path"
                rates.update_layout(title=title, yaxis_title="%")
                _show(rates, note)
    if "curve" in kinds:
        with slots[slot]:
            curve = subset_by_geography(yield_curve(), "country", geography)
            if curve.empty:
                _missing_series(geography)
            else:
                fig = go.Figure()
                for country, group in curve.groupby("country", sort=False):
                    fig.add_trace(go.Scatter(
                        x=group["tenor"], y=group["yield_pct"], name=str(country), mode="lines+markers",
                    ))
                title = "Sovereign yield curve" if curve["country"].nunique() > 1 else f"{curve['country'].iloc[0]} yield curve"
                fig.update_layout(title=title, yaxis_title="%")
                _show(fig, note)


def _time_slice(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    window_from = filters.get("time_from")
    window_to = filters.get("time_to") if window_from is not None else None
    if window_from is None and window_to is None:
        return frame
    return subset_by_time(frame, window_from, window_to)


def _tail_window(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "1M":
        return frame.tail(6)
    if window == "3M":
        return frame.tail(9)
    return frame


def markets_charts(filters: dict) -> None:
    kinds = panel_chart_kinds("markets", filters.get("category_id"))
    geography = filters.get("geography")
    note = f"Simulated series for {geography}." if geography else "Simulated series. Not a live quote."
    if not kinds:
        st.info("This category has no separate chart. The event list below is filtered.")
        return
    if "ribbon" in kinds:
        ribbon = ticker_ribbon()
        chips = []
        for row in ribbon.itertuples():
            tone = "good" if row.change_pct >= 0 else "critical"
            chips.append(f":{ 'green' if tone == 'good' else 'red' }-badge[{row.symbol} {row.change_pct:+.1f}%]")
        st.markdown(" ".join(chips))
        st.caption("Ticker ribbon uses the simulated batch. Treat every print as delayed demo data.")
    window = "1Y"
    if "liquidity" in kinds or "breadth" in kinds:
        window = st.radio("Chart window", ["1M", "3M", "1Y"], horizontal=True, key="mkt-window")
        st.caption(f"Window {window} rescales the demo liquidity and breadth paths. It does not load a live history.")
    _paired_markets(filters, kinds, geography, note, window)
    if "crypto" in kinds:
        st.subheader("Crypto and alternatives")
        st.dataframe(crypto_board(), hide_index=True, width="stretch")
        st.caption("Private-market items in category 18 stay on a slower cadence than these liquid prints.")


def _paired_markets(filters: dict, kinds: frozenset[str], geography: str | None, note: str, window: str) -> None:
    pairs = (
        ("map", "liquidity"),
        ("breadth", "vol"),
        ("commodities", "fx"),
    )
    for left_kind, right_kind in pairs:
        shown = [kind for kind in (left_kind, right_kind) if kind in kinds]
        if not shown:
            continue
        slots = st.columns(2) if len(shown) == 2 else (st.container(),)
        slot = 0
        for kind in shown:
            with slots[slot]:
                slot += 1
                _market_chart(kind, filters, geography, note, window)


def _market_chart(kind: str, filters: dict, geography: str | None, note: str, window: str) -> None:
    if kind == "map":
        world = subset_by_geography(market_map(), "market", geography)
        if world.empty:
            _missing_series(geography)
            return
        colors = [t.GOOD if value >= 0 else t.CRITICAL for value in world["change_pct"]]
        fig = go.Figure(go.Bar(x=world["market"], y=world["change_pct"], marker_color=colors))
        title = f"{world['market'].iloc[0]} session change" if len(world) == 1 else "Global market map, session change"
        fig.update_layout(title=title, yaxis_title="%")
        _show(fig, note)
        return
    if kind == "liquidity":
        liq = _tail_window(_time_slice(liquidity_gauge(), filters), window)
        if liq.empty:
            _missing_series(geography)
            return
        gauge = go.Figure(go.Scatter(x=liq["date"], y=liq["conditions_index"], mode="lines", fill="tozeroy"))
        gauge.update_layout(title="Financial conditions (higher = easier, simulated)")
        _show(gauge, note)
        st.metric("Latest conditions", f"{liq['conditions_index'].iloc[-1]:.2f}")
        return
    if kind == "breadth":
        wide = _tail_window(_time_slice(breadth(), filters), window)
        if wide.empty:
            _missing_series(geography)
            return
        fig = go.Figure(go.Scatter(x=wide["date"], y=wide["pct_above_200d"], mode="lines", name="% above 200-day"))
        fig.update_layout(title="Equity breadth", yaxis_title="% of members")
        _show(fig, note)
        return
    if kind == "vol":
        vol = volatility_curve()
        fig = go.Figure(go.Scatter(x=vol["tenor"], y=vol["implied_vol"], mode="lines+markers"))
        fig.update_layout(title="Volatility curve", yaxis_title="Implied vol")
        _show(fig, note)
        return
    if kind == "commodities":
        goods = commodities()
        fig = go.Figure(go.Bar(x=goods["commodity"], y=goods["change_pct"]))
        fig.update_layout(title="Commodity dashboard, session change", yaxis_title="%")
        _show(fig, note)
        return
    fx = fx_matrix()
    fig = go.Figure(go.Bar(x=fx["pair"], y=fx["change_pct"]))
    fig.update_layout(title="FX matrix, session change", yaxis_title="%")
    _show(fig, note)


def corporate_charts(events, filters: dict) -> None:
    kinds = panel_chart_kinds("corporate", filters.get("category_id"))
    owned = kinds & {"earnings", "guidance", "calendar"}
    if not owned:
        if not kinds:
            st.info("This category has no separate chart. The event list below is filtered.")
        return
    if "earnings" in kinds or "guidance" in kinds:
        board = earnings_board()
        slots = st.columns(2) if {"earnings", "guidance"} <= kinds else (st.container(),)
        slot = 0
        if "earnings" in kinds:
            with slots[slot]:
                slot += 1
                colors = [t.GOOD if value >= 0 else t.CRITICAL for value in board["surprise_pct"]]
                beat = go.Figure(go.Bar(x=board["symbol"], y=board["surprise_pct"], marker_color=colors))
                beat.update_layout(title="Beat / miss vs consensus, simulated %", yaxis_title="%")
                _show(beat)
        if "guidance" in kinds:
            with slots[slot]:
                revisions = go.Figure(go.Bar(x=board["symbol"], y=board["revision"], name="Estimate revision"))
                revisions.update_layout(title="Estimate revision leaderboard", yaxis_title="Index points")
                _show(revisions)
            st.subheader("Guidance tracker")
            st.dataframe(board[["symbol", "guidance", "surprise_pct", "revision"]], hide_index=True, width="stretch")
    if "calendar" in kinds:
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


def risk_charts(filters: dict) -> None:
    kinds = panel_chart_kinds("risk", filters.get("category_id"))
    if "spreads" not in kinds:
        if not kinds:
            st.info("This category has no separate chart. The event list below is filtered.")
        return
    spreads = _time_slice(credit_spreads(), filters)
    if spreads.empty:
        _missing_series(filters.get("geography"))
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spreads["date"], y=spreads["ig_bps"], name="Investment grade"))
    fig.add_trace(go.Scatter(x=spreads["date"], y=spreads["hy_bps"], name="High yield"))
    fig.update_layout(title="Credit spreads", yaxis_title="bps")
    _show(fig)


def sector_charts(filters: dict) -> None:
    kinds = panel_chart_kinds("sector", filters.get("category_id"))
    if not kinds:
        st.info("This category has no separate chart. The event list below is filtered.")
        return
    frame = sector_performance()
    sector = filters.get("sector")
    if sector:
        frame = frame.loc[frame["sector"] == sector].reset_index(drop=True)
    if {"performance", "revisions", "valuation"} & kinds:
        if frame.empty:
            st.info(f"No simulated sector series for {sector}. The event list still uses this filter.")
        else:
            if "performance" in kinds:
                window = st.radio("Relative window", ["1W", "1M", "3M", "1Y"], horizontal=True, key="sec-window")
                colors = [t.GOOD if value >= 0 else t.CRITICAL for value in frame[window]]
                heat = go.Figure(go.Bar(x=frame["sector"], y=frame[window], marker_color=colors))
                heat.update_layout(title=f"Sector relative performance, {window}", yaxis_title="%")
                _show(heat)
            slots = st.columns(2) if {"revisions", "valuation"} <= kinds else (st.container(),)
            slot = 0
            if "revisions" in kinds:
                with slots[slot]:
                    slot += 1
                    rev = go.Figure(go.Bar(x=frame["sector"], y=frame["revision"]))
                    rev.update_layout(title="Earnings revision trend", yaxis_title="Simulated revision")
                    _show(rev)
            if "valuation" in kinds:
                with slots[slot]:
                    val = go.Figure(go.Bar(x=frame["sector"], y=frame["valuation_percentile"]))
                    val.update_layout(title="Valuation percentile", yaxis_title="Percentile")
                    _show(val)
    if "themes" in kinds:
        st.subheader("Structural themes")
        st.dataframe(themes(), hide_index=True, width="stretch")
    if "constituents" in kinds:
        constituents = sector_constituents()
        names_for = list(constituents)
        if sector and sector in constituents:
            names_for = [sector]
        picked = names_for[0] if len(names_for) == 1 else st.selectbox("Inspect a sector", names_for, key="sec-names")
        names = constituents[picked]
        if names:
            st.write("Demo constituents: " + ", ".join(names))
        else:
            st.caption("No demo constituent is mapped to this sector. The sector row is still in the catalog.")


def portfolio_charts(holdings: list[Holding], book_choice: str, filters: dict) -> None:
    kinds = panel_chart_kinds("portfolio", filters.get("category_id"))
    if not holdings:
        st.warning("Holdings are unavailable. Connect a book, enter holdings, or switch to the demo book.")
        return
    if not kinds:
        st.info("This category has no separate chart. The event list below is filtered.")
        return
    geography = filters.get("geography")
    sector = filters.get("sector")
    scoped = holdings
    if geography:
        scoped = [row for row in scoped if row.country == geography]
    if sector:
        scoped = [row for row in scoped if row.sector == sector]
    holding_kinds = kinds & {"allocation", "weights", "concentration"}
    if holding_kinds and not scoped:
        st.info("No holdings match these filters. The event list still uses them.")
    elif holding_kinds:
        frame = pd.DataFrame([row.__dict__ for row in scoped])
        if "allocation" in kinds:
            tree = go.Figure(go.Treemap(
                labels=frame["symbol"] + " " + frame["sector"],
                parents=[""] * len(frame),
                values=frame["market_value"].clip(lower=0),
                textinfo="label+percent root",
            ))
            tree.update_layout(title="Allocation")
            _show(tree)
        if "weights" in kinds:
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
        if "concentration" in kinds:
            top = frame.sort_values("weight_pct", ascending=False).head(5)
            st.subheader("Concentration")
            st.dataframe(top[["symbol", "name", "weight_pct", "sector", "country"]], hide_index=True, width="stretch")
    if "history" in kinds:
        if book_choice == "demo":
            history = _time_slice(portfolio_history(), filters)
            if history.empty:
                _missing_series(geography)
            else:
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
                if scoped:
                    perf = sector_performance().set_index("sector")["1M"]
                    rows = []
                    for holding in scoped:
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
    book_kinds = kinds & {"factors", "funds"}
    if book_kinds:
        slots = st.columns(2) if len(book_kinds) == 2 else (st.container(),)
        slot = 0
        if "factors" in kinds:
            with slots[slot]:
                slot += 1
                factors = factor_exposures()
                factor_fig = go.Figure(go.Bar(x=factors["factor"], y=factors["exposure"]))
                factor_fig.update_layout(title="Factor exposure, demo model")
                _show(factor_fig)
        if "funds" in kinds:
            with slots[slot]:
                st.subheader("Fund quality")
                st.dataframe(fund_quality(), hide_index=True, width="stretch")
                st.caption("Premium, expense ratio, and tracking error are simulated fund-file fields.")
    if "stress" in kinds:
        st.subheader("Scenario stress")
        st.dataframe(stress_tests(), hide_index=True, width="stretch")
        st.caption("Stress results are a fixed demo grid. VaR and expected shortfall elsewhere in the catalog carry the same limitation: they are model output, not a guarantee.")
