"""Small reusable pieces: KPI rows, status pills, formatted tables."""

import pandas as pd
import streamlit as st

from ui.components import theme as t


def kpi_row(metrics: dict, keys: list[tuple[str, str, str]]) -> None:
    """keys: (metric key, label, kind) where kind is pct | ratio | money | int."""
    cols = st.columns(len(keys))
    for col, (key, label, kind) in zip(cols, keys):
        v = metrics.get(key)
        if kind == "pct":
            text = t.pct(v, already_pct=True)
        elif kind == "money":
            text = t.money(v)
        elif kind == "int":
            text = f"{int(v):,}" if v is not None else "—"
        else:
            text = t.num(v)
        col.metric(label, text, border=True)


STANDARD_KPIS = [
    ("total_return_pct", "Total return", "pct"),
    ("cagr_pct", "CAGR", "pct"),
    ("sharpe", "Sharpe", "ratio"),
    ("max_drawdown_pct", "Max drawdown", "pct"),
    ("win_rate_pct", "Win rate", "pct"),
    ("num_trades", "Trades", "int"),
]


def pill(label: str, value: str, state: str = "neutral") -> str:
    """Markdown badge; state: good | warning | critical | neutral."""
    color = {"good": "green", "warning": "orange", "critical": "red"}.get(state, "gray")
    icon = {"good": ":material/check_circle:", "warning": ":material/warning:",
            "critical": ":material/error:"}.get(state, ":material/radio_button_unchecked:")
    return f":{color}-badge[{icon} {label}: {value}]"


def trades_table(trades: pd.DataFrame, height: int = 320) -> None:
    if trades.empty:
        st.caption("No closed trades.")
        return
    df = trades.copy()
    df["return_pct"] = (df["exit_price"] / df["entry_price"] - 1) * 100
    df.loc[df["direction"] == "SHORT", "return_pct"] *= -1
    df["days"] = (pd.to_datetime(df["exit_time"]) - pd.to_datetime(df["entry_time"])).dt.days
    cols = ["exit_time", "symbol", "direction", "entry_time", "quantity", "entry_price",
            "exit_price", "return_pct", "net_pnl", "days"]
    st.dataframe(
        df[cols].sort_values("exit_time", ascending=False),
        hide_index=True, height=height, width="stretch",
        column_config={
            "exit_time": st.column_config.DateColumn("Exit"),
            "entry_time": st.column_config.DateColumn("Entry"),
            "symbol": "Symbol", "direction": "Side",
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f"),
            "entry_price": st.column_config.NumberColumn("Entry $", format="%.2f"),
            "exit_price": st.column_config.NumberColumn("Exit $", format="%.2f"),
            "return_pct": st.column_config.NumberColumn("Return", format="%.2f%%"),
            "net_pnl": st.column_config.NumberColumn("Net P&L", format="dollar"),
            "days": st.column_config.NumberColumn("Days held"),
        },
    )


def positions_table(positions: pd.DataFrame, height: int = 320, limit: int | None = None) -> None:
    if positions.empty:
        st.caption("No open positions.")
        return
    df = positions.copy()
    if limit:
        df = df.head(limit)
    cols = [c for c in ["symbol", "sector", "quantity", "avg_price", "last_price", "market_value",
                        "weight", "unrealised_pnl", "unrealised_pct", "opened_at"] if c in df.columns]
    df["weight"] = df["weight"] * 100
    df["unrealised_pct"] = df["unrealised_pct"] * 100
    st.dataframe(
        df[cols], hide_index=True, height=height, width="stretch",
        column_config={
            "symbol": "Symbol", "sector": "Sector",
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f"),
            "avg_price": st.column_config.NumberColumn("Avg cost", format="dollar"),
            "last_price": st.column_config.NumberColumn("Last", format="dollar"),
            "market_value": st.column_config.NumberColumn("Value", format="dollar"),
            "weight": st.column_config.ProgressColumn("Weight", format="%.2f%%", min_value=0,
                                                      max_value=max(3.0, float(df["weight"].max()))),
            "unrealised_pnl": st.column_config.NumberColumn("Unrealised", format="dollar"),
            "unrealised_pct": st.column_config.NumberColumn("Unrealised %", format="%.1f%%"),
            "opened_at": st.column_config.DateColumn("Opened"),
        },
    )


CHECK_LABELS = {
    "max_open_positions": "Position limit",
    "max_gross_exposure": "Gross exposure cap",
    "max_sector_pct": "Sector cap",
    "max_correlation": "Correlation filter",
    "drawdown_halt": "Drawdown halt",
    "halted": "Halted",
    "no_price": "No price",
    "zero_size": "Zero size",
    "no_position": "Exit with no position",
    "already_in_position": "Already in position",
}


def decisions_table(decisions: pd.DataFrame, height: int = 320) -> None:
    if decisions.empty:
        st.caption("No signals.")
        return
    df = decisions.copy()
    df["reason"] = df["check"].map(lambda c: CHECK_LABELS.get(c, c) if c else "")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["limit"] = pd.to_numeric(df["limit"], errors="coerce")
    st.dataframe(
        df[["timestamp", "symbol", "direction", "action", "reason", "value", "limit", "detail"]]
        .sort_values("timestamp", ascending=False),
        hide_index=True, height=height, width="stretch",
        column_config={
            "timestamp": st.column_config.DateColumn("Date"),
            "symbol": "Symbol", "direction": "Signal", "action": "Outcome",
            "reason": "Reason", "detail": "Detail",
            "value": st.column_config.NumberColumn("Value", format="%.3f"),
            "limit": st.column_config.NumberColumn("Limit", format="%.3f"),
        },
    )
