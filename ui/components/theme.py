"""Colours, Plotly template and number formatting shared by every page."""

import math

import plotly.graph_objects as go
import plotly.io as pio

# Categorical slots, fixed order (validated palette) — strategy always slot 1
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STRATEGY, BENCH_1, BENCH_2 = SERIES[0], SERIES[1], SERIES[2]

GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
POS_TEXT, NEG_TEXT = "#006300", "#b42727"

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"

# Diverging blue ↔ gray ↔ red (positive = blue, negative = red)
DIVERGING = [[0.0, "#b42727"], [0.25, "#e98c8b"], [0.5, "#f0efec"], [0.75, "#86b6ef"], [1.0, "#1c5cab"]]
SEQUENTIAL = [[0.0, "#cde2fb"], [0.5, "#5598e7"], [1.0, "#104281"]]

pio.templates["algo"] = go.layout.Template(
    layout=dict(
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12, color=INK_2),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=SERIES,
        margin=dict(l=8, r=8, t=44, b=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", bordercolor=AXIS, font=dict(color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=INK_2), bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED),
                   showgrid=False),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED)),
        title=dict(font=dict(size=14, color=INK), x=0, xanchor="left"),
    )
)
pio.templates.default = "algo"


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def pct(v, digits: int = 1, already_pct: bool = False) -> str:
    if not _ok(v):
        return "—"
    return f"{(v if already_pct else v * 100):.{digits}f}%"


def money(v, digits: int = 0) -> str:
    if not _ok(v):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e6:
        return f"{sign}${v / 1e6:.2f}M"
    if v >= 1e4:
        return f"{sign}${v / 1e3:.1f}K"
    return f"{sign}${v:,.{digits}f}"


def num(v, digits: int = 2) -> str:
    return f"{v:,.{digits}f}" if _ok(v) else "—"
