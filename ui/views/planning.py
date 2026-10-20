"""Planning: target mix for a portfolio, saved as JSON, compared with holdings."""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from agents.agno.llm import generate
from data.feed import DataFeed
from execution.portfolio_service import PortfolioBackend
from planning.backtest import BENCHMARK, SLEEVE_PROXIES, proxy_symbols, run_plan_backtest
from planning.optimize import PlanTargets, improve_plan
from planning.model import (
    EQUITY_BUCKETS,
    HORIZONS,
    SECTORS,
    STATUSES,
    UNSET,
    Plan,
    Slice,
    allocation_drift,
    portfolio_nav,
    slice_errors,
)
from planning.store import PlanStore
from ui.components import charts
from ui.components import state
from ui.components import theme as t
from ui.components import widgets

store = PlanStore()
backend = PortfolioBackend()


def _slices_from_editor(frame: pd.DataFrame) -> list[Slice]:
    rows: list[Slice] = []
    for record in frame.to_dict(orient="records"):
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        rows.append(Slice(
            name=name,
            target=float(record.get("target") or 0),
            floor=float(record.get("floor") or 0),
            ceiling=float(record.get("ceiling") or 0),
        ))
    return rows


def _slice_frame(rows: list[Slice]) -> pd.DataFrame:
    return pd.DataFrame([row.to_dict() for row in rows], columns=["name", "target", "floor", "ceiling"])


def _sum_caption(rows: list[Slice], what: str) -> None:
    total = sum(row.target for row in rows)
    if abs(total - 100) < 0.05:
        st.caption(f"{what} targets add up to {total:.1f}%.")
    else:
        st.warning(f"{what} targets add up to {total:.1f}%. They should add up to 100%.", icon=":material/warning:")


def _pie(pairs: list[tuple[str, float | None]], title: str, *, height: int = 340) -> go.Figure | None:
    labels: list[str] = []
    values: list[float] = []
    for name, value in pairs:
        if value is None or value <= 0:
            continue
        labels.append(name)
        values.append(float(value))
    if not values:
        return None
    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.52,
        sort=False,
        direction="clockwise",
        marker=dict(
            colors=[t.SERIES[i % len(t.SERIES)] for i in range(len(labels))],
            line=dict(color=t.SURFACE, width=2),
        ),
        textinfo="percent",
        textposition="inside",
        insidetextorientation="horizontal",
        hovertemplate="%{label}: %{percent} (%{value:,.1f})<extra></extra>",
        domain=dict(x=[0, 1], y=[0.34, 1]),
    ))
    fig.update_layout(
        title=title,
        height=height,
        showlegend=True,
        hovermode="closest",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=0.28,
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(l=8, r=8, t=44, b=8),
    )
    return fig


def _show_pie(pairs: list[tuple[str, float | None]], title: str, *, height: int = 340, key: str) -> None:
    fig = _pie(pairs, title, height=height)
    if fig is None:
        st.caption(f"{title}: nothing to chart yet.")
        return
    st.plotly_chart(fig, width="stretch", key=key)


def _holding_values(snapshot) -> dict[str, float]:
    frame = PortfolioBackend.normalise_positions(snapshot.positions)
    held: dict[str, float] = {}
    if frame.empty:
        return held
    for record in frame.to_dict(orient="records"):
        symbol = str(record.get("symbol") or "").upper()
        if symbol:
            held[symbol] = held.get(symbol, 0.0) + float(record.get("market_value") or 0)
    return held


def _band_chart(rows: list[dict], title: str) -> go.Figure:
    """Allowed range from floor to ceiling, with the target and the actual weight."""
    ordered = list(reversed(rows))
    names = [row["name"] for row in ordered]
    floors = [row["floor"] for row in ordered]
    span = [max(0.0, row["ceiling"] - row["floor"]) for row in ordered]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Floor to ceiling",
        y=names,
        x=span,
        base=floors,
        orientation="h",
        marker=dict(color=t.GRID, cornerradius=3),
        customdata=[row["ceiling"] for row in ordered],
        hovertemplate="%{y}: %{base:.1f}% to %{customdata:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        name="Target",
        x=[row["target"] for row in ordered],
        y=names,
        mode="markers",
        marker=dict(symbol="diamond", size=11, color=t.INK),
        hovertemplate="%{y} target %{x:.1f}%<extra></extra>",
    ))
    actual_x, actual_y, actual_color = [], [], []
    for row in ordered:
        if row.get("actual") is None:
            continue
        actual_x.append(row["actual"])
        actual_y.append(row["name"])
        if row["status"] in {"below floor", "above ceiling"}:
            actual_color.append(t.CRITICAL)
        elif row["status"] in {"underweight", "overweight"}:
            actual_color.append(t.WARNING)
        else:
            actual_color.append(t.GOOD)
    if actual_x:
        fig.add_trace(go.Scatter(
            name="Actual",
            x=actual_x,
            y=actual_y,
            mode="markers",
            marker=dict(symbol="circle", size=10, color=actual_color, line=dict(color="white", width=1)),
            hovertemplate="%{y} actual %{x:.1f}%<extra></extra>",
        ))
    fig.update_layout(
        title=title,
        height=max(260, 42 * len(names) + 90),
        xaxis_ticksuffix="%",
        xaxis_title="Percent of portfolio",
        hovermode="closest",
        barmode="overlay",
        margin=dict(l=8, r=8, t=44, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, xanchor="left"),
    )
    return fig


def _gap_chart(rows: list[dict], title: str) -> go.Figure | None:
    usable = [row for row in rows if row.get("gap") is not None]
    if not usable:
        return None
    usable.sort(key=lambda row: row["gap"])
    gaps = [row["gap"] for row in usable]
    fig = go.Figure(go.Bar(
        y=[row["name"] for row in usable],
        x=gaps,
        orientation="h",
        marker=dict(
            color=[t.CRITICAL if gap < 0 else t.STRATEGY for gap in gaps],
            cornerradius=3,
        ),
        text=[f"{gap:+.1f}" for gap in gaps],
        textposition="auto",
        textfont=dict(color=t.INK_2),
        hovertemplate="%{y}: %{x:+.1f} percentage points<extra></extra>",
    ))
    fig.add_vline(x=0, line=dict(color=t.INK_2, width=1))
    span = max(abs(gap) for gap in gaps)
    fig.update_layout(
        title=title,
        height=max(260, 42 * len(usable) + 90),
        xaxis_title="Actual minus target (percentage points)",
        xaxis_range=[-(span * 1.35), span * 1.35],
        hovermode="closest",
        showlegend=False,
        margin=dict(l=8, r=36, t=44, b=8),
    )
    return fig


def _holding_chart(names: list[dict], cap: float) -> go.Figure | None:
    if not names:
        return None
    ordered = sorted(names, key=lambda row: row["weight"])
    weights = [row["weight"] for row in ordered]
    fig = go.Figure(go.Bar(
        y=[row["symbol"] for row in ordered],
        x=weights,
        orientation="h",
        marker=dict(
            color=[t.CRITICAL if row["over_cap"] else t.STRATEGY for row in ordered],
            cornerradius=3,
        ),
        hovertemplate="%{y}: %{x:.1f}% of the portfolio<extra></extra>",
    ))
    if cap > 0:
        fig.add_vline(
            x=cap,
            line=dict(color=t.CRITICAL, dash="dash", width=1.5),
            annotation_text=f"cap {cap:.0f}%",
            annotation_font_color=t.INK_2,
        )
    xmax = max([cap, *weights, 1]) * 1.25
    fig.update_layout(
        title="Holding size against the single-name cap",
        height=max(220, 36 * len(ordered) + 80),
        xaxis_ticksuffix="%",
        xaxis_range=[0, xmax],
        hovermode="closest",
        showlegend=False,
        margin=dict(l=8, r=8, t=44, b=8),
    )
    return fig


def _drift_chart(rows: list[dict], title: str) -> go.Figure:
    names = [row["name"] for row in rows][::-1]
    target = [row["target"] for row in rows][::-1]
    actual = [0 if row["actual"] is None else row["actual"] for row in rows][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Target", y=names, x=target, orientation="h",
        marker=dict(color=t.BENCH_1, cornerradius=3),
        hovertemplate="%{y} target %{x:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Actual", y=names, x=actual, orientation="h",
        marker=dict(color=t.STRATEGY, cornerradius=3),
        hovertemplate="%{y} actual %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        barmode="group", title=title, height=max(240, 36 * len(rows) + 80),
        xaxis_ticksuffix="%", xaxis_title="Percent", hovermode="closest",
        margin=dict(l=8, r=8, t=44, b=8),
    )
    return fig


def _invested_chart(rows: list[dict], currency: str) -> go.Figure | None:
    shown = [
        row for row in rows
        if (row.get("invested") or 0) > 0 or (row.get("target_value") or 0) > 0
    ]
    if not shown:
        return None
    names = [row["name"] for row in shown][::-1]
    invested = [row.get("invested") or 0 for row in shown][::-1]
    targets = [0 if row.get("target_value") is None else row["target_value"] for row in shown][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Target", y=names, x=targets, orientation="h",
        marker=dict(color=t.BENCH_1, cornerradius=3),
        hovertemplate="%{y} target " + currency + " %{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Invested", y=names, x=invested, orientation="h",
        marker=dict(color=t.STRATEGY, cornerradius=3),
        hovertemplate="%{y} invested " + currency + " %{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        barmode="group",
        title="Invested and target",
        height=max(240, 36 * len(shown) + 80),
        xaxis_title=currency,
        hovermode="closest",
        margin=dict(l=8, r=8, t=44, b=8),
    )
    return fig


def _status_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    order = ["name", "target", "floor", "ceiling", "actual", "gap", "status"]
    return frame[[column for column in order if column in frame.columns]]


def _number_columns() -> dict:
    return {
        "target": st.column_config.NumberColumn("Target %", min_value=0, max_value=100, step=1, format="%.1f"),
        "floor": st.column_config.NumberColumn("Floor %", min_value=0, max_value=100, step=1, format="%.1f"),
        "ceiling": st.column_config.NumberColumn("Ceiling %", min_value=0, max_value=100, step=1, format="%.1f"),
        "actual": st.column_config.NumberColumn("Actual %", format="%.1f"),
        "gap": st.column_config.NumberColumn("Gap", format="%+.1f"),
    }


st.title("Planning")
st.caption("Target mix for how the portfolio should be split. Plans are saved as JSON in data/plans.")

if st.session_state.pop("_clear_plan", False):
    st.session_state.pop("plan_id", None)

plans = store.list_plans()
create_col, select_col = st.columns([1, 2])
with create_col:
    with st.form("create_plan", clear_on_submit=True, border=False):
        new_name = st.text_input("New plan", placeholder="Core portfolio")
        submitted = st.form_submit_button("Create plan", type="primary", width="stretch")
    if submitted:
        if not new_name.strip():
            st.warning("Give the plan a name.")
        else:
            created = store.create(new_name.strip())
            st.session_state["plan_id"] = created.id
            st.session_state.pop("_plan_form", None)
            st.rerun()

if not plans:
    st.info("Create a plan to set geography, asset, and sector targets.", icon=":material/info:")
    st.stop()

ids = [plan.id for plan in plans]
labels = {plan.id: f"{plan.name}  ·  {plan.status}" for plan in plans}
if st.session_state.get("plan_id") not in ids:
    st.session_state["plan_id"] = ids[0]

with select_col:
    st.selectbox(
        "Saved plans",
        ids,
        format_func=lambda plan_id: labels[plan_id],
        key="plan_id",
    )

plan = store.load(st.session_state["plan_id"])
if plan is None:
    st.error("That plan file could not be read.")
    st.stop()


def _bind_form(current: Plan) -> None:
    """Load form widgets when the selected plan changes. Later reruns keep edits."""
    if st.session_state.get("_plan_form") == current.id:
        return
    st.session_state["_plan_form"] = current.id
    st.session_state["plan_name"] = current.name
    st.session_state["plan_purpose"] = current.purpose
    st.session_state["plan_horizon"] = current.horizon if current.horizon in HORIZONS else HORIZONS[2]
    st.session_state["plan_status"] = current.status if current.status in STATUSES else "draft"
    st.session_state["plan_currency"] = current.currency
    st.session_state["plan_max_name"] = float(current.max_single_name_pct)
    st.session_state["plan_max_sector"] = float(current.max_sector_pct)
    st.session_state["plan_band"] = float(current.rebalance_band_pct)
    st.session_state["plan_contribution"] = float(current.monthly_contribution)
    st.session_state["plan_notes"] = current.notes
    try:
        st.session_state["plan_review"] = date.fromisoformat(current.review_date) if current.review_date else None
    except ValueError:
        st.session_state["plan_review"] = None


_bind_form(plan)

pending_mix = st.session_state.pop("_apply_plan_mix", None)
if isinstance(pending_mix, dict) and pending_mix.get("id") == plan.id:
    rev = int(st.session_state.get("_mix_rev", 0)) + 1
    st.session_state["_mix_rev"] = rev
    pending_mix["rev"] = rev
    st.session_state["_sleeve_override"] = pending_mix
    st.session_state["plan_band"] = float(pending_mix["rebalance_band_pct"])
    st.session_state["_mix_notice"] = (
        "The adjusted sleeve mix is in the editor. Save the plan when you want the JSON file updated."
    )

sleeve_override = st.session_state.get("_sleeve_override")
if not isinstance(sleeve_override, dict) or sleeve_override.get("id") != plan.id:
    sleeve_override = None

header = st.columns(4)
header[0].metric("Status", plan.status, border=True)
header[1].metric("Horizon", plan.horizon, border=True)
header[2].metric("Review", plan.review_date or "not set", border=True)
header[3].metric("Monthly contribution", f"{plan.currency} {plan.monthly_contribution:,.0f}", border=True)

st.subheader("Saved plans")
st.caption("Sleeve targets already saved. The charts next to the tables follow what you are editing, before you save.")
for start in range(0, len(plans), 3):
    row = plans[start:start + 3]
    cols = st.columns(len(row))
    for col, saved in zip(cols, row):
        with col:
            _show_pie(
                [(item.name, item.target) for item in saved.buckets],
                saved.name,
                height=300,
                key=f"saved-pie-{saved.id}",
            )

st.subheader("Portfolio")
actual = st.toggle(
    "Use the live portfolio",
    value=False,
    help="Off uses the paper portfolio. On uses the connected IBKR account, or the last saved live snapshot.",
)
if actual:
    snapshot = backend.get_snapshot(True, st.session_state.get("ibkr_trader"))
    if not snapshot.connected:
        snapshot = backend.get_persisted_live_snapshot()
else:
    snapshot = backend.get_paper_snapshot()
held = _holding_values(snapshot)
_, cash = portfolio_nav(snapshot.summary, sum(held.values()))
portfolio_pairs: list[tuple[str, float | None]] = list(held.items())
if cash:
    portfolio_pairs.append(("Cash", cash))
port_col, _ = st.columns([1, 2])
with port_col:
    _show_pie(portfolio_pairs, "Holdings and cash", key="portfolio-pie")

identity, rules = st.columns([1.2, 1])
with identity:
    st.subheader("Plan")
    name = st.text_input("Name", key="plan_name")
    purpose = st.text_input("Purpose", key="plan_purpose")
    horizon = st.selectbox("Horizon", HORIZONS, key="plan_horizon")
    status = st.selectbox("Status", STATUSES, key="plan_status")
    currency = st.text_input("Currency", key="plan_currency")

with rules:
    st.subheader("Rules")
    max_name = st.number_input("Max single holding %", min_value=0.0, max_value=100.0, step=1.0, key="plan_max_name")
    max_sector = st.number_input("Max sector % of portfolio", min_value=0.0, max_value=100.0, step=1.0, key="plan_max_sector")
    band = st.number_input("Rebalance band (percentage points)", min_value=0.0, max_value=50.0, step=1.0, key="plan_band")
    review = st.date_input("Next review", key="plan_review")
    contribution = st.number_input("Monthly contribution", min_value=0.0, step=100.0, key="plan_contribution")
    notes = st.text_area("Notes", height=88, key="plan_notes")

mix_notice = st.session_state.pop("_mix_notice", None)
if mix_notice:
    st.success(mix_notice)

st.subheader("Where the money sits")
st.caption("Local, global, and emerging markets, plus bonds, gold, and cash. Each row is a percent of the whole portfolio. The pie updates when the table does.")
sleeve_table, sleeve_pie = st.columns([1.35, 1])
sleeve_source = plan.buckets
sleeve_key = f"buckets-{plan.id}-{plan.updated_at}"
if sleeve_override:
    sleeve_source = [Slice.from_dict(row) for row in sleeve_override.get("buckets") or []]
    sleeve_key = f"buckets-{plan.id}-mix-{sleeve_override.get('rev')}"
with sleeve_table:
    bucket_editor = st.data_editor(
        _slice_frame(sleeve_source),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=sleeve_key,
        column_config={"name": "Sleeve", **_number_columns()},
    )
    buckets = _slices_from_editor(bucket_editor)
    _sum_caption(buckets, "Sleeve")
with sleeve_pie:
    _show_pie([(item.name, item.target) for item in buckets], "Sleeve targets", key="edit-sleeve-pie")

st.subheader("Sectors")
st.caption("Percent of the equity sleeves only (local, developed global, and emerging).")
sector_table, sector_pie = st.columns([1.35, 1])
with sector_table:
    sector_editor = st.data_editor(
        _slice_frame(plan.sectors),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"sectors-{plan.id}-{plan.updated_at}",
        column_config={"name": "Sector", **_number_columns()},
    )
    sectors = _slices_from_editor(sector_editor)
    _sum_caption(sectors, "Sector")
with sector_pie:
    _show_pie([(item.name, item.target) for item in sectors], "Sector targets", key="edit-sector-pie")

st.subheader("Holdings")
st.caption("Tag each holding so drift can compare the portfolio with this plan. Tags are saved with the plan.")
symbols = sorted(set(held) | set(plan.classifications))
bucket_names = list(dict.fromkeys(row.name for row in buckets))
sector_names = list(dict.fromkeys([row.name for row in sectors] + list(SECTORS)))
tag_rows = []
for symbol in symbols:
    tag = plan.classifications.get(symbol, {})
    bucket = tag.get("bucket") or UNSET
    sector = tag.get("sector") or UNSET
    if bucket not in bucket_names and bucket != UNSET:
        bucket_names.append(bucket)
    tag_rows.append({
        "symbol": symbol,
        "market_value": held.get(symbol),
        "bucket": bucket if bucket in [UNSET, *bucket_names] else UNSET,
        "sector": sector if sector in [UNSET, *sector_names] else UNSET,
    })
tag_frame = pd.DataFrame(tag_rows, columns=["symbol", "market_value", "bucket", "sector"])
edited_tags = st.data_editor(
    tag_frame,
    hide_index=True,
    width="stretch",
    disabled=["symbol", "market_value"],
    key=f"tags-{plan.id}-{plan.updated_at}-{int(actual)}",
    column_config={
        "symbol": "Symbol",
        "market_value": st.column_config.NumberColumn("Market value", format="dollar"),
        "bucket": st.column_config.SelectboxColumn("Sleeve", options=[UNSET, *bucket_names], required=True),
        "sector": st.column_config.SelectboxColumn("Sector", options=[UNSET, *sector_names], required=True),
    },
)

classifications: dict[str, dict[str, str]] = {}
for record in edited_tags.to_dict(orient="records"):
    symbol = str(record.get("symbol") or "").upper()
    if not symbol:
        continue
    bucket = str(record.get("bucket") or "")
    sector = str(record.get("sector") or "")
    if bucket == UNSET and sector == UNSET:
        continue
    classifications[symbol] = {
        "bucket": "" if bucket == UNSET else bucket,
        "sector": "" if sector == UNSET else sector,
    }

draft = Plan(
    id=plan.id,
    name=name.strip() or plan.name,
    purpose=purpose.strip(),
    horizon=horizon,
    status=status,
    currency=currency.strip() or "USD",
    buckets=buckets,
    sectors=sectors,
    max_single_name_pct=float(max_name),
    max_sector_pct=float(max_sector),
    rebalance_band_pct=float(band),
    review_date=review.isoformat() if isinstance(review, date) else "",
    monthly_contribution=float(contribution),
    notes=notes.strip(),
    classifications=classifications,
    created_at=plan.created_at,
    updated_at=plan.updated_at,
)

errors = slice_errors(draft.buckets, "Sleeves") + slice_errors(draft.sectors, "Sectors")
if not draft.name:
    errors.append("The plan needs a name.")
for message in errors:
    st.error(message)

save_col, delete_col = st.columns([1, 4])
with save_col:
    if st.button("Save plan", type="primary", width="stretch", disabled=bool(errors)):
        store.save(draft, make_active=draft.status == "active")
        st.session_state.pop("_sleeve_override", None)
        st.rerun()
with delete_col:
    if st.button("Delete plan"):
        st.session_state["confirm_delete"] = plan.id

if st.session_state.get("confirm_delete") == plan.id:
    st.warning(f"Delete {plan.name}? The JSON file is removed.")
    if st.button("Confirm delete"):
        store.delete(plan.id)
        st.session_state["_clear_plan"] = True
        st.session_state.pop("confirm_delete", None)
        st.session_state.pop("_plan_form", None)
        st.session_state.pop("_sleeve_override", None)
        st.rerun()

drift = allocation_drift(draft, snapshot.positions, snapshot.summary)

st.subheader("Invested in this plan")
st.caption(
    "A holding counts once it is tagged to a sleeve. "
    "Target dollars apply each sleeve target to the portfolio value."
)
share = None if not drift["nav"] else drift["invested"] / drift["nav"] * 100
shortfall = None
if drift["nav"] is not None:
    target_invested = sum(
        row["target_value"] or 0
        for row in drift["rows"]
        if row["name"] != "Cash"
    )
    shortfall = target_invested - drift["invested"]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Invested", t.money(drift["invested"]), border=True)
k2.metric("Cash", "—" if drift["cash"] is None else t.money(drift["cash"]), border=True)
k3.metric("Outside the plan", t.money(drift["outside"]), border=True)
k4.metric("Share of portfolio", "—" if share is None else f"{share:.1f}%", border=True)
if shortfall is not None and shortfall > 1:
    st.caption(f"{t.money(shortfall)} still to invest to reach the non-cash sleeve targets.")
elif shortfall is not None:
    st.caption("Tagged holdings cover the non-cash sleeve targets.")
if not drift["invested"] and drift["outside"]:
    st.info("Tag the holdings above to count them in this plan.", icon=":material/sell:")

invested_rows = []
for row in drift["rows"]:
    target_value = row.get("target_value")
    invested_amount = row.get("invested") or 0
    invested_rows.append({
        "sleeve": row["name"],
        "invested": invested_amount,
        "target_value": target_value,
        "gap_value": None if target_value is None else invested_amount - target_value,
    })
money_chart = _invested_chart(drift["rows"], draft.currency)
chart_col, table_col = st.columns([1.15, 1])
with chart_col:
    if money_chart is None:
        st.caption("Invested and target: nothing to chart yet.")
    else:
        st.plotly_chart(money_chart, width="stretch", key="invested-bars")
with table_col:
    st.dataframe(
        pd.DataFrame(invested_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "sleeve": "Sleeve",
            "invested": st.column_config.NumberColumn(f"Invested ({draft.currency})", format="dollar"),
            "target_value": st.column_config.NumberColumn(f"Target ({draft.currency})", format="dollar"),
            "gap_value": st.column_config.NumberColumn(f"Gap ({draft.currency})", format="%+d"),
        },
    )

st.subheader("Drift")
if drift["basis"] == "nav":
    st.caption(
        f"Actual weights use portfolio value {draft.currency} {drift['nav']:,.0f}. "
        f"Cash is that value minus holdings ({draft.currency} {drift['cash']:,.0f})."
    )
else:
    st.caption("Portfolio value was not available, so weights are a share of holdings and cash is unknown.")

if drift["unclassified"]:
    st.warning(
        "These holdings are not tagged yet, so they sit outside the sleeves: "
        + ", ".join(drift["unclassified"]),
        icon=":material/warning:",
    )

if drift["fill_next"]:
    first = drift["fill_next"][0]
    amount = f"{draft.currency} {draft.monthly_contribution:,.0f}" if draft.monthly_contribution else "New money"
    st.markdown(widgets.pill("Fill next", first, "warning") + "  " + f"{amount} goes to the most underweight sleeve.")
else:
    st.markdown(widgets.pill("Rebalance", "inside the band", "good"))

outside = [row["name"] for row in drift["rows"] if row["status"] in {"below floor", "above ceiling"}]
if outside:
    st.markdown(widgets.pill("Outside floor or ceiling", ", ".join(outside), "critical"))

untagged = sum(row["weight"] for row in drift["names"] if row["symbol"] in set(drift["unclassified"]))
actual_sleeves = [(row["name"], row["actual"]) for row in drift["rows"]]
if untagged > 0:
    actual_sleeves.append(("Untagged", untagged))
actual_sectors = [(row["name"], row["actual"]) for row in drift["sectors"]]

mix_plan, mix_book, mix_sector = st.columns(3)
with mix_plan:
    _show_pie([(item.name, item.target) for item in draft.buckets], "Plan sleeves", height=320, key="drift-plan-pie")
with mix_book:
    _show_pie(actual_sleeves, "Portfolio sleeves", height=320, key="drift-book-pie")
with mix_sector:
    _show_pie(actual_sectors, "Portfolio sectors", height=320, key="drift-sector-pie")

st.caption("Gray bar is the allowed range. Diamond is the target. A dot is the portfolio: green inside the rebalance band, amber off target, red outside the floor or ceiling.")
band_col, gap_col = st.columns(2)
with band_col:
    st.plotly_chart(_band_chart(drift["rows"], "Sleeve range"), width="stretch", key="sleeve-band")
with gap_col:
    gap = _gap_chart(drift["rows"], "Sleeve gap")
    if gap is None:
        st.caption("Sleeve gap: actual weights are not available yet.")
    else:
        st.plotly_chart(gap, width="stretch", key="sleeve-gap")

left, right = st.columns(2)
with left:
    st.plotly_chart(_drift_chart(drift["rows"], "Sleeves, target and actual"), width="stretch", key="sleeve-bars")
    st.dataframe(_status_frame(drift["rows"]), hide_index=True, width="stretch", column_config=_number_columns())
with right:
    equity_rows = [row for row in drift["sectors"]]
    st.plotly_chart(_drift_chart(equity_rows, "Sectors, share of tagged equity"), width="stretch", key="sector-bars")
    sector_gap = _gap_chart(equity_rows, "Sector gap")
    if sector_gap is not None:
        st.plotly_chart(sector_gap, width="stretch", key="sector-gap")
    st.dataframe(_status_frame(equity_rows), hide_index=True, width="stretch", column_config=_number_columns())

holding_fig = _holding_chart(drift["names"], draft.max_single_name_pct)
if holding_fig is not None:
    st.plotly_chart(holding_fig, width="stretch", key="holding-cap")

hot = [row for row in drift["names"] if row["over_cap"]]
if hot:
    detail = ", ".join(f"{row['symbol']} {row['weight']:.1f}%" for row in hot)
    st.error(f"Above the {draft.max_single_name_pct:.0f}% single-holding cap: {detail}")

sector_hot = [
    row for row in drift["sectors"]
    if row.get("portfolio_pct") is not None and row["portfolio_pct"] > draft.max_sector_pct
]
if sector_hot:
    detail = ", ".join(f"{row['name']} {row['portfolio_pct']:.1f}%" for row in sector_hot)
    st.error(f"Above the {draft.max_sector_pct:.0f}% sector cap of the whole portfolio: {detail}")

st.caption(f"Equity sleeves counted in the sector mix: {', '.join(sorted(EQUITY_BUCKETS))}.")
st.caption(f"File: data/plans/{plan.id}.json · updated {plan.updated_at or 'not saved'}")

st.subheader("Backtest")
st.caption(
    "Each sleeve is one ETF: "
    + ", ".join(f"{name} {symbol}" for name, symbol in SLEEVE_PROXIES.items() if symbol)
    + ". Cash earns nothing. "
    "On the first session of a month, the contribution goes to sleeves below target. "
    "At month-end the mix is reset to target when a sleeve is outside its band or its floor and ceiling. "
    "Sector targets are not separate trades."
)
bt1, bt2, bt3, bt4 = st.columns(4)
bt_start = bt1.date_input("Start", value=date(2019, 1, 1), key="plan_bt_start")
bt_end = bt2.date_input("End", value=date.today(), key="plan_bt_end")
bt_cash = bt3.number_input("Starting cash", min_value=1.0, value=100_000.0, step=10_000.0, format="%.0f", key="plan_bt_cash")
bt_contribution = bt4.number_input(
    "Monthly contribution",
    min_value=0.0,
    value=float(draft.monthly_contribution),
    step=100.0,
    format="%.0f",
    key="plan_bt_contribution",
)
if st.button("Backtest this plan", type="primary", icon=":material/play_arrow:"):
    if bt_start >= bt_end:
        st.error("Start must be before end.")
    else:
        symbols = proxy_symbols(draft)
        end_exclusive = (pd.Timestamp(bt_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        with st.spinner("Loading sleeve prices and running the backtest…"):
            try:
                feed = DataFeed(state.cache_dir())
                feed.download(symbols, start=str(bt_start), end=end_exclusive)
                prices = feed.load_prices(symbols, start=str(bt_start), end=end_exclusive)
                result = run_plan_backtest(
                    draft,
                    prices,
                    initial_cash=float(bt_cash),
                    monthly_contribution=float(bt_contribution),
                )
            except Exception as exc:
                result = None
                st.error(str(exc))
        if result is not None:
            st.session_state["plan_backtest"] = result
            st.session_state["plan_backtest_id"] = draft.id

result = st.session_state.get("plan_backtest")
if result is not None and st.session_state.get("plan_backtest_id") == draft.id:
    metrics = result.metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Final value", t.money(metrics.get("final_equity")), border=True)
    m2.metric("Total return", "—" if metrics.get("total_return_pct") is None else f"{metrics['total_return_pct']:.1f}%", border=True)
    m3.metric("CAGR", "—" if metrics.get("cagr_pct") is None else f"{metrics['cagr_pct']:.1f}%", border=True)
    m4.metric("Max drawdown", "—" if metrics.get("max_drawdown_pct") is None else f"{metrics['max_drawdown_pct']:.1f}%", border=True)
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Sharpe", "—" if metrics.get("sharpe") is None else f"{metrics['sharpe']:.2f}", border=True)
    n2.metric("Rebalances", metrics.get("rebalances", 0), border=True)
    n3.metric("Contributed", t.money(result.contributed), border=True)
    bench = metrics.get("benchmark_return_pct")
    n4.metric(f"{BENCHMARK} return", "—" if bench is None else f"{bench:.1f}%", border=True)
    for note in result.notes:
        st.caption(note)
    bench_frame = pd.DataFrame({BENCHMARK: result.benchmark}) if not result.benchmark.empty else None
    st.plotly_chart(
        charts.equity_vs_benchmarks(result.equity, bench_frame, "Plan value vs SPY"),
        width="stretch",
        key="plan-bt-equity",
    )
    weight_fig = go.Figure()
    for i, column in enumerate(result.weights.columns):
        weight_fig.add_trace(go.Scatter(
            x=result.weights.index,
            y=result.weights[column] * 100,
            name=column,
            mode="lines",
            stackgroup="one",
            line=dict(width=0.4, color=t.SERIES[i % len(t.SERIES)]),
            hovertemplate="%{y:.1f}%",
        ))
    weight_fig.update_layout(
        title="Sleeve weights",
        height=320,
        yaxis_ticksuffix="%",
        yaxis_range=[0, 100],
        hovermode="x unified",
        margin=dict(l=8, r=8, t=44, b=8),
    )
    st.plotly_chart(weight_fig, width="stretch", key="plan-bt-weights")
    if result.rebalance_dates:
        shown = ", ".join(day.strftime("%Y-%m-%d") for day in result.rebalance_dates[:12])
        extra = len(result.rebalance_dates) - 12
        st.caption("Month-end rebalances: " + shown + (f" and {extra} more." if extra > 0 else "."))
    else:
        st.caption("No month-end rebalance. Sleeves stayed inside the band.")

st.subheader("Improve with the model")
st.caption(
    "Backtest the mix in the editor, then ask the sidebar model to adjust sleeve targets "
    "until every selected target passes or the iteration limit is reached. "
    "The first pass is the current mix and does not call the model. "
    "The JSON file changes only when you save."
)
opt1, opt2, opt3, opt4, opt5 = st.columns(5)
use_cagr = opt1.checkbox("Min CAGR %", value=True, key="opt_use_cagr")
cagr_value = opt1.number_input(
    "CAGR at least",
    min_value=-50.0,
    max_value=100.0,
    value=8.0,
    step=0.5,
    key="opt_cagr",
    disabled=not use_cagr,
)
use_drawdown = opt2.checkbox("Max drawdown %", value=True, key="opt_use_dd")
drawdown_value = opt2.number_input(
    "Drawdown at most",
    min_value=0.0,
    max_value=100.0,
    value=20.0,
    step=1.0,
    key="opt_dd",
    disabled=not use_drawdown,
    help="Passes when max drawdown is at or below this ceiling.",
)
use_sharpe = opt3.checkbox("Min Sharpe", value=False, key="opt_use_sharpe")
sharpe_value = opt3.number_input(
    "Sharpe at least",
    min_value=-2.0,
    max_value=5.0,
    value=0.5,
    step=0.1,
    key="opt_sharpe",
    disabled=not use_sharpe,
)
use_return = opt4.checkbox("Min total return %", value=False, key="opt_use_return")
return_value = opt4.number_input(
    "Total return at least",
    min_value=-100.0,
    max_value=1000.0,
    value=50.0,
    step=5.0,
    key="opt_return",
    disabled=not use_return,
)
max_loops = opt5.number_input(
    "Max iterations",
    min_value=1,
    max_value=8,
    value=3,
    step=1,
    key="opt_iterations",
    help="From 1 to 8. Each iteration is one backtest. The model is called only when a target is still missed and iterations remain.",
)
review_model = (st.session_state.get("llm_model") or "").strip()
review_provider = (st.session_state.get("llm_provider") or "").strip()
if review_model:
    st.caption(f"Reviews use {review_provider} · {review_model}.")
else:
    st.caption("Choose a model in the sidebar. The loop will not invent a review without one.")

if st.button("Run improvement loop", type="primary", icon=":material/auto_fix_high:"):
    selected = PlanTargets(
        min_cagr_pct=float(cagr_value) if use_cagr else None,
        max_drawdown_pct=float(drawdown_value) if use_drawdown else None,
        min_sharpe=float(sharpe_value) if use_sharpe else None,
        min_total_return_pct=float(return_value) if use_return else None,
    )
    loops = int(max_loops)
    if not selected.enabled():
        st.warning("Turn on at least one target.")
    elif loops < 1 or loops > 8:
        st.warning("Max iterations must be from 1 to 8.")
    elif not review_provider or not review_model:
        st.error("Choose a model in the sidebar before running the improvement loop.")
    elif bt_start >= bt_end:
        st.error("Start must be before end.")
    else:
        symbols = proxy_symbols(draft)
        end_exclusive = (pd.Timestamp(bt_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        def _review(prompt: str) -> str:
            return generate(prompt, provider=review_provider, model=review_model, max_tokens=1200)

        with st.status("Running the improvement loop…", expanded=True) as status_box:
            try:
                feed = DataFeed(state.cache_dir())
                feed.download(symbols, start=str(bt_start), end=end_exclusive)
                prices = feed.load_prices(symbols, start=str(bt_start), end=end_exclusive)

                def _note(record) -> None:
                    cagr = record.metrics.get("cagr_pct")
                    drawdown = record.metrics.get("max_drawdown_pct")
                    cagr_text = "—" if cagr is None else f"{cagr:.1f}%"
                    drawdown_text = "—" if drawdown is None else f"{drawdown:.1f}%"
                    verdict = "passed" if record.passed else "missed"
                    status_box.write(
                        f"Iteration {record.number}: CAGR {cagr_text}, max drawdown {drawdown_text}, {verdict}."
                    )

                outcome = improve_plan(
                    draft,
                    prices,
                    initial_cash=float(bt_cash),
                    monthly_contribution=float(bt_contribution),
                    targets=selected,
                    max_iterations=loops,
                    llm=_review,
                    on_iteration=_note,
                )
                if outcome.status == "met":
                    status_box.update(label="Targets met", state="complete")
                elif outcome.status == "llm_error":
                    status_box.update(label="Model error", state="error")
                else:
                    status_box.update(label="Iteration limit reached", state="complete")
            except Exception as exc:
                outcome = None
                status_box.update(label="Improvement loop stopped", state="error")
                st.error(str(exc))
        if outcome is not None:
            st.session_state["plan_optimize"] = outcome
            st.session_state["plan_optimize_id"] = draft.id
            st.session_state["plan_optimize_token"] = st.session_state.get("plan_optimize_token", 0) + 1

outcome = st.session_state.get("plan_optimize")
if outcome is not None and st.session_state.get("plan_optimize_id") == draft.id:
    if outcome.status == "met":
        st.success(f"Targets met on iteration {outcome.best_index + 1}.")
    elif outcome.status == "llm_error":
        error_text = outcome.iterations[-1].adjustment_error or "The model returned an error."
        st.error(error_text)
        st.warning(
            f"The target was not reached. Best completed mix is iteration {outcome.best_index + 1} "
            f"by {outcome.primary}."
        )
    else:
        st.warning(
            f"Used all {len(outcome.iterations)} iterations. The target was not reached. "
            f"Best mix is iteration {outcome.best_index + 1} by {outcome.primary}."
        )
    table_rows = []
    for record in outcome.iterations:
        metrics = record.metrics
        table_rows.append({
            "iteration": record.number,
            "cagr_pct": metrics.get("cagr_pct"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "sharpe": metrics.get("sharpe"),
            "total_return_pct": metrics.get("total_return_pct"),
            "passed": "Yes" if record.passed else "No",
            "gaps": "; ".join(record.failures),
            "rationale": record.rationale,
            "adjustment": record.adjustment_error,
        })
    st.dataframe(
        pd.DataFrame(table_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "iteration": "Iteration",
            "cagr_pct": st.column_config.NumberColumn("CAGR %", format="%.2f"),
            "max_drawdown_pct": st.column_config.NumberColumn("Max drawdown %", format="%.2f"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "total_return_pct": st.column_config.NumberColumn("Total return %", format="%.2f"),
            "passed": "Passed",
            "gaps": "Gaps",
            "rationale": "Rationale",
            "adjustment": "Adjustment",
        },
    )
    labels = []
    for index, record in enumerate(outcome.iterations):
        mark = " · best" if index == outcome.best_index else ""
        labels.append(f"Iteration {record.number}{mark}")
    token = st.session_state.get("plan_optimize_token", 0)
    picked = st.selectbox(
        "Mix to apply",
        list(range(len(outcome.iterations))),
        index=outcome.best_index,
        format_func=lambda index: labels[index],
        key=f"opt-mix-{draft.id}-{token}",
    )
    chosen = outcome.iterations[picked]
    st.dataframe(
        pd.DataFrame(chosen.buckets),
        hide_index=True,
        width="stretch",
        column_config={
            "name": "Sleeve",
            "target": st.column_config.NumberColumn("Target %", format="%.1f"),
            "floor": st.column_config.NumberColumn("Floor %", format="%.1f"),
            "ceiling": st.column_config.NumberColumn("Ceiling %", format="%.1f"),
        },
    )
    st.caption(
        f"Rebalance band {chosen.rebalance_band_pct:g} percentage points. "
        "Use this mix updates the sleeve table and the rebalance band. The JSON file stays as it is until you save."
    )
    if st.button("Use this mix"):
        st.session_state["_apply_plan_mix"] = {
            "id": draft.id,
            "buckets": chosen.buckets,
            "rebalance_band_pct": chosen.rebalance_band_pct,
        }
        st.rerun()
