"""Plotly figures used across pages. Every function returns a go.Figure."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ui.components import theme as t


def equity_vs_benchmarks(equity: pd.Series, benchmarks: pd.DataFrame | None,
                         title: str = "Growth of $1M") -> go.Figure:
    """Strategy and benchmarks indexed to the strategy's starting equity (one axis)."""
    fig = go.Figure()
    base = float(equity.iloc[0])
    colors = [t.BENCH_1, t.BENCH_2] + t.SERIES[3:]
    if benchmarks is not None and not benchmarks.empty:
        for i, col in enumerate(benchmarks.columns):
            s = benchmarks[col].dropna()
            if s.empty:
                continue
            s = s / s.iloc[0] * base
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, name=col, mode="lines",
                line=dict(width=2, color=colors[i % len(colors)]),
                hovertemplate="%{y:$,.0f}",
            ))
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values, name="Strategy", mode="lines",
        line=dict(width=2.5, color=t.STRATEGY), hovertemplate="%{y:$,.0f}",
    ))
    fig.update_layout(title=title, height=340, yaxis_tickformat="$,.3~s")
    return fig


def drawdown(dd: pd.Series, title: str = "Drawdown from peak") -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=dd.index, y=dd.values, mode="lines", name="Drawdown", fill="tozeroy",
        line=dict(width=1.5, color=t.CRITICAL), fillcolor="rgba(208,59,59,0.15)",
        hovertemplate="%{y:.1%}",
    ))
    fig.update_layout(title=title, height=200, yaxis_tickformat=".0%", showlegend=False)
    return fig


def line(series: pd.Series, title: str, fmt: str = ".0%", color: str = t.STRATEGY,
         height: int = 220, hline: float | None = None, hline_label: str = "") -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=series.index, y=series.values, mode="lines", name=series.name or title,
        line=dict(width=2, color=color), hovertemplate=f"%{{y:{fmt}}}",
    ))
    if hline is not None:
        fig.add_hline(y=hline, line=dict(color=t.MUTED, dash="dot", width=1),
                      annotation_text=hline_label, annotation_font_color=t.INK_2)
    fig.update_layout(title=title, height=height, yaxis_tickformat=fmt, showlegend=False)
    return fig


def monthly_heatmap(table: pd.DataFrame, title: str = "Monthly returns") -> go.Figure:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    table = table.reindex(columns=range(1, 13))
    z = table.values
    lim = np.nanmax(np.abs(z)) if np.isfinite(z).any() else 0.01
    text = [[("" if np.isnan(v) else f"{v:.1%}") for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=months, y=[str(y) for y in table.index], text=text, texttemplate="%{text}",
        colorscale=t.DIVERGING, zmin=-lim, zmax=lim, xgap=2, ygap=2,
        hovertemplate="%{y} %{x}: %{z:.2%}<extra></extra>", showscale=False,
        textfont=dict(color=t.INK, size=11),
    ))
    fig.update_layout(title=title, height=60 + 34 * len(table), hovermode="closest",
                      yaxis=dict(autorange="reversed", showgrid=False))
    return fig


def sector_exposure(exposure: dict, cap: float | None, title: str = "Sector exposure") -> go.Figure:
    s = pd.Series(exposure, dtype=float).sort_values()
    fig = go.Figure(go.Bar(
        x=s.values, y=s.index, orientation="h", marker=dict(color=t.STRATEGY, cornerradius=4),
        hovertemplate="%{y}: %{x:.1%}<extra></extra>", text=[f"{v:.1%}" for v in s.values],
        textposition="outside", textfont=dict(color=t.INK_2),
    ))
    if cap:
        fig.add_vline(x=cap, line=dict(color=t.CRITICAL, dash="dash", width=1.5),
                      annotation_text=f"cap {cap:.0%}", annotation_font_color=t.INK_2)
    xmax = max([cap or 0] + list(s.values)) * 1.25 if len(s) else 0.3
    fig.update_layout(title=title, height=max(220, 40 + 28 * len(s)), xaxis_tickformat=".0%",
                      xaxis_range=[0, xmax], showlegend=False, hovermode="closest", bargap=0.35)
    return fig


def counts_bar(counts: pd.Series, title: str, color: str = t.STRATEGY) -> go.Figure:
    counts = counts.sort_values()
    fig = go.Figure(go.Bar(
        x=counts.values, y=[str(i) for i in counts.index], orientation="h",
        marker=dict(color=color, cornerradius=4), text=counts.values, textposition="outside",
        textfont=dict(color=t.INK_2), hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    fig.update_layout(title=title, height=max(200, 40 + 30 * len(counts)), showlegend=False,
                      hovermode="closest", bargap=0.35,
                      xaxis_range=[0, (counts.max() if len(counts) else 1) * 1.2])
    return fig


def correlation_heatmap(corr: pd.DataFrame, title: str = "Correlation of holdings") -> go.Figure:
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=corr.columns, y=corr.index, colorscale=t.DIVERGING, zmin=-1, zmax=1,
        hovertemplate="%{y} / %{x}: %{z:.2f}<extra></extra>", xgap=1, ygap=1,
        colorbar=dict(thickness=10, tickfont=dict(color=t.MUTED)),
    ))
    size = max(320, min(720, 18 * len(corr) + 120))
    fig.update_layout(title=title, height=size, hovermode="closest",
                      yaxis=dict(autorange="reversed", showgrid=False), xaxis=dict(showgrid=False))
    return fig


def candles_with_signals(df: pd.DataFrame, fast: pd.Series, slow: pd.Series,
                         entries: pd.DataFrame, exits: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Price", increasing_line_color="#1c5cab", decreasing_line_color="#b42727",
        increasing_fillcolor="#86b6ef", decreasing_fillcolor="#e98c8b", line=dict(width=1),
    ))
    fig.add_trace(go.Scatter(x=fast.index, y=fast.values, name=f"Fast MA", mode="lines",
                             line=dict(width=2, color=t.BENCH_1)))
    fig.add_trace(go.Scatter(x=slow.index, y=slow.values, name=f"Slow MA", mode="lines",
                             line=dict(width=2, color=t.SERIES[6])))
    if not entries.empty:
        fig.add_trace(go.Scatter(
            x=entries.index, y=entries["price"], name="Buy", mode="markers",
            marker=dict(symbol="triangle-up", size=12, color=t.GOOD, line=dict(width=1.5, color="white")),
        ))
    if not exits.empty:
        fig.add_trace(go.Scatter(
            x=exits.index, y=exits["price"], name="Exit", mode="markers",
            marker=dict(symbol="triangle-down", size=12, color=t.CRITICAL, line=dict(width=1.5, color="white")),
        ))
    fig.update_layout(title=title, height=460, xaxis_rangeslider_visible=False)
    return fig
