"""Chart tables for Market Monitor panels. All series are simulated."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from market_monitor.catalog import AS_OF


def _rng(seed: int) -> np.random.Generator:
    """Fresh generator so a simulated series is the same on every call.

    A shared generator advances on each Streamlit rerun, so the same filter
    would draw a different chart.
    """
    return np.random.default_rng(seed)


def _dates(n: int = 18) -> list[datetime]:
    start = AS_OF - timedelta(days=30 * (n - 1))
    return [start + timedelta(days=30 * i) for i in range(n)]


def macro_surprise() -> pd.DataFrame:
    countries = ["United States", "Euro area", "United Kingdom", "Japan", "China", "India"]
    indicators = ["CPI", "Core CPI", "Payrolls", "PMI", "Retail sales", "GDP"]
    rng = _rng(20)
    rows = []
    for country in countries:
        for indicator in indicators:
            yoy = round(float(rng.normal(0, 0.6)), 2)
            mom = round(yoy / 3 + float(rng.normal(0, 0.15)), 2)
            rows.append({"country": country, "indicator": indicator, "yoy": yoy, "mom": mom})
    return pd.DataFrame(rows)


def growth_inflation() -> pd.DataFrame:
    return pd.DataFrame([
        {"country": "United States", "gdp": 2.1, "inflation": 2.4},
        {"country": "Euro area", "gdp": 0.8, "inflation": 2.1},
        {"country": "United Kingdom", "gdp": 1.1, "inflation": 2.6},
        {"country": "Japan", "gdp": 0.6, "inflation": 1.8},
        {"country": "China", "gdp": 4.4, "inflation": 0.4},
        {"country": "India", "gdp": 6.5, "inflation": 3.2},
    ])


def rate_path() -> pd.DataFrame:
    dates = _dates(8)
    series = {
        "United States": (
            [4.50, 4.50, 4.25, 4.25, 4.00, 4.00, 3.75, 3.75],
            [4.48, 4.42, 4.20, 4.05, 3.90, 3.82, 3.70, 3.60],
        ),
        "Euro area": (
            [3.50, 3.25, 3.00, 2.75, 2.50, 2.50, 2.25, 2.25],
            [3.40, 3.10, 2.85, 2.60, 2.40, 2.30, 2.15, 2.10],
        ),
        "United Kingdom": (
            [4.75, 4.50, 4.50, 4.25, 4.00, 4.00, 3.75, 3.75],
            [4.60, 4.40, 4.20, 4.00, 3.85, 3.70, 3.60, 3.50],
        ),
        "Japan": (
            [0.25, 0.25, 0.50, 0.50, 0.50, 0.75, 0.75, 0.75],
            [0.30, 0.40, 0.45, 0.55, 0.60, 0.70, 0.80, 0.85],
        ),
        "China": (
            [3.35, 3.35, 3.10, 3.10, 3.00, 3.00, 2.90, 2.90],
            [3.20, 3.10, 3.00, 2.95, 2.90, 2.85, 2.80, 2.75],
        ),
        "India": (
            [6.50, 6.50, 6.50, 6.25, 6.25, 6.00, 6.00, 5.75],
            [6.40, 6.35, 6.20, 6.10, 6.00, 5.90, 5.80, 5.70],
        ),
    }
    rows = []
    for country, (policy, implied) in series.items():
        for date, policy_rate, futures_implied in zip(dates, policy, implied):
            rows.append({
                "date": date,
                "country": country,
                "policy_rate": policy_rate,
                "futures_implied": futures_implied,
            })
    return pd.DataFrame(rows)


def yield_curve() -> pd.DataFrame:
    tenors = ["1M", "3M", "2Y", "5Y", "10Y", "30Y"]
    curves = {
        "United States": [4.15, 4.05, 3.72, 3.68, 3.95, 4.22],
        "Euro area": [3.20, 3.05, 2.40, 2.35, 2.55, 2.80],
        "United Kingdom": [4.40, 4.30, 3.90, 3.85, 4.05, 4.40],
        "Japan": [0.20, 0.25, 0.55, 0.75, 1.05, 2.10],
        "China": [1.50, 1.55, 1.60, 1.70, 1.85, 2.10],
        "India": [6.40, 6.35, 6.20, 6.25, 6.45, 6.80],
    }
    rows = []
    for country, yields in curves.items():
        for tenor, yield_pct in zip(tenors, yields):
            rows.append({"country": country, "tenor": tenor, "yield_pct": yield_pct})
    return pd.DataFrame(rows)


def regional_scorecard() -> pd.DataFrame:
    return pd.DataFrame([
        {"region": "United States", "growth": "Slowing, still positive", "inflation": "Near 2%", "policy": "Easing bias", "watch": "Labor revisions"},
        {"region": "Euro area", "growth": "Soft", "inflation": "Close to target", "policy": "On hold", "watch": "Energy"},
        {"region": "United Kingdom", "growth": "Modest", "inflation": "Above target", "policy": "Easing", "watch": "Fiscal"},
        {"region": "China", "growth": "Uneven", "inflation": "Low", "policy": "Targeted support", "watch": "Property"},
        {"region": "India", "growth": "Firm", "inflation": "Contained", "policy": "Meeting ahead", "watch": "Local flows"},
        {"region": "Japan", "growth": "Modest", "inflation": "Around 2%", "policy": "Normalization", "watch": "Yen"},
    ])


# Charts that belong to a Global Macro category. None means every category.
MACRO_CHARTS = {
    None: frozenset({"surprise", "quadrant", "rates", "curve", "scorecard"}),
    1: frozenset({"surprise", "quadrant"}),
    2: frozenset({"rates", "curve"}),
    5: frozenset(),
    11: frozenset({"quadrant", "scorecard"}),
}


def macro_chart_kinds(category_id: int | None) -> frozenset[str]:
    return MACRO_CHARTS.get(category_id, MACRO_CHARTS[None])


# Charts that belong to a category on the other monitor panels.
# None means every chart for that panel. An unknown category uses the same set.
PANEL_CHARTS = {
    "markets": {
        None: frozenset({"ribbon", "map", "liquidity", "breadth", "vol", "commodities", "fx", "crypto"}),
        6: frozenset({"liquidity"}),
        7: frozenset({"ribbon", "map", "breadth", "vol"}),
        9: frozenset({"commodities"}),
        10: frozenset({"fx"}),
        18: frozenset({"crypto"}),
    },
    "corporate": {
        None: frozenset({"earnings", "guidance", "calendar", "governance"}),
        3: frozenset({"earnings", "guidance", "calendar"}),
        14: frozenset({"governance"}),
    },
    "risk": {
        None: frozenset({"spreads", "geography", "holdings", "geopolitics", "hazards"}),
        4: frozenset({"geography", "geopolitics"}),
        12: frozenset({"spreads"}),
        16: frozenset({"geography", "hazards"}),
    },
    "sector": {
        None: frozenset({"performance", "revisions", "valuation", "themes", "constituents"}),
        8: frozenset({"performance", "revisions", "valuation", "constituents"}),
        15: frozenset({"themes"}),
    },
    "portfolio": {
        None: frozenset({"allocation", "weights", "history", "factors", "funds", "stress", "concentration"}),
        13: frozenset({"funds"}),
        20: frozenset({"allocation", "weights", "history", "factors", "stress", "concentration"}),
    },
}


def panel_chart_kinds(panel_id: str, category_id: int | None) -> frozenset[str]:
    table = PANEL_CHARTS[panel_id]
    return table.get(category_id, table[None])


def subset_by_geography(frame: pd.DataFrame, column: str, geography: str | None) -> pd.DataFrame:
    if not geography:
        return frame.reset_index(drop=True)
    return frame.loc[frame[column] == geography].reset_index(drop=True)


def subset_by_time(frame: pd.DataFrame, time_from: datetime | None, time_to: datetime | None) -> pd.DataFrame:
    out = frame
    if time_from is not None:
        out = out.loc[pd.to_datetime(out["date"], utc=True) >= pd.Timestamp(time_from)]
    if time_to is not None:
        out = out.loc[pd.to_datetime(out["date"], utc=True) <= pd.Timestamp(time_to)]
    return out.reset_index(drop=True)


def ticker_ribbon() -> pd.DataFrame:
    return pd.DataFrame([
        {"symbol": "SPX", "last": 5720, "change_pct": 0.4},
        {"symbol": "NDX", "last": 20110, "change_pct": 0.7},
        {"symbol": "RUT", "last": 2210, "change_pct": -0.3},
        {"symbol": "SX5E", "last": 4980, "change_pct": 0.2},
        {"symbol": "NKY", "last": 39200, "change_pct": -0.4},
        {"symbol": "TLT", "last": 98.4, "change_pct": 0.3},
        {"symbol": "DXY", "last": 103.2, "change_pct": -0.1},
        {"symbol": "WTI", "last": 78.4, "change_pct": 1.1},
        {"symbol": "Gold", "last": 2680, "change_pct": 0.5},
        {"symbol": "BTC", "last": 64200, "change_pct": -1.4},
    ])


def market_map() -> pd.DataFrame:
    return pd.DataFrame([
        {"market": "United States", "change_pct": 0.4},
        {"market": "Euro area", "change_pct": 0.2},
        {"market": "United Kingdom", "change_pct": -0.1},
        {"market": "Japan", "change_pct": -0.4},
        {"market": "China", "change_pct": 0.6},
        {"market": "India", "change_pct": 0.5},
        {"market": "Brazil", "change_pct": -0.8},
        {"market": "Taiwan", "change_pct": 0.9},
    ])


def liquidity_gauge() -> pd.DataFrame:
    dates = _dates(12)
    rng = _rng(21)
    return pd.DataFrame({
        "date": dates,
        "conditions_index": np.round(np.linspace(-0.4, 0.3, len(dates)) + rng.normal(0, 0.05, len(dates)), 2),
    })


def breadth() -> pd.DataFrame:
    dates = _dates(12)
    rng = _rng(22)
    return pd.DataFrame({
        "date": dates,
        "pct_above_200d": np.clip(np.round(62 + rng.normal(0, 4, len(dates)), 1), 20, 90),
        "advance_decline": np.round(rng.normal(0.1, 0.4, len(dates)), 2),
    })


def volatility_curve() -> pd.DataFrame:
    return pd.DataFrame({
        "tenor": ["1W", "1M", "2M", "3M", "6M", "1Y"],
        "implied_vol": [14.2, 15.1, 16.0, 16.8, 17.4, 18.1],
    })


def commodities() -> pd.DataFrame:
    return pd.DataFrame([
        {"commodity": "WTI", "change_pct": 1.1, "level": 78.4},
        {"commodity": "Brent", "change_pct": 0.9, "level": 82.1},
        {"commodity": "Henry Hub", "change_pct": -2.4, "level": 2.85},
        {"commodity": "Gold", "change_pct": 0.5, "level": 2680},
        {"commodity": "Copper", "change_pct": 0.8, "level": 4.32},
        {"commodity": "Lithium", "change_pct": -1.2, "level": 10.4},
    ])


def fx_matrix() -> pd.DataFrame:
    return pd.DataFrame([
        {"pair": "DXY", "level": 103.2, "change_pct": -0.1},
        {"pair": "EUR/USD", "level": 1.086, "change_pct": 0.2},
        {"pair": "USD/JPY", "level": 149.4, "change_pct": 0.3},
        {"pair": "GBP/USD", "level": 1.312, "change_pct": 0.1},
        {"pair": "USD/INR", "level": 83.9, "change_pct": 0.0},
        {"pair": "USD/CNY", "level": 7.12, "change_pct": -0.1},
    ])


def crypto_board() -> pd.DataFrame:
    return pd.DataFrame([
        {"asset": "BTC", "change_pct": -1.4, "note": "Simulated liquid print"},
        {"asset": "ETH", "change_pct": -1.8, "note": "Simulated liquid print"},
        {"asset": "Spot ETF flow", "change_pct": 0.2, "note": "Simulated daily flow, $ millions scaled"},
        {"asset": "Stablecoin float", "change_pct": 0.1, "note": "Simulated issuance minus redemptions"},
    ])


def credit_spreads() -> pd.DataFrame:
    dates = _dates(16)
    rng = _rng(23)
    return pd.DataFrame({
        "date": dates,
        "ig_bps": np.round(95 + rng.normal(0, 2, len(dates)).cumsum() * 0.3, 1),
        "hy_bps": np.round(320 + rng.normal(0, 4, len(dates)).cumsum() * 0.4, 1),
    })


def sector_performance() -> pd.DataFrame:
    sectors = [
        "Information Technology", "Financials", "Health Care", "Energy", "Industrials",
        "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
        "Real Estate", "Communication Services",
    ]
    rng = _rng(24)
    rows = []
    for sector in sectors:
        base = float(rng.normal(0, 1.2))
        rows.append({
            "sector": sector,
            "1W": round(base * 0.4, 2),
            "1M": round(base, 2),
            "3M": round(base * 2.1, 2),
            "1Y": round(base * 4.0, 2),
            "revision": round(float(rng.normal(0, 0.4)), 2),
            "valuation_percentile": int(np.clip(50 + rng.normal(0, 18), 5, 95)),
        })
    return pd.DataFrame(rows)


def sector_constituents() -> dict[str, tuple[str, ...]]:
    return {
        "Information Technology": ("AAPL", "MSFT", "NVDA"),
        "Financials": ("JPM",),
        "Health Care": ("UNH",),
        "Energy": ("XOM",),
        "Industrials": ("CAT",),
        "Consumer Discretionary": ("AAPL",),
        "Consumer Staples": (),
        "Utilities": (),
        "Materials": (),
        "Real Estate": (),
        "Communication Services": (),
    }


def themes() -> pd.DataFrame:
    return pd.DataFrame([
        {"theme": "AI and data centers", "adoption": "High spend, uneven monetization", "valuation": "Elevated"},
        {"theme": "Electrification", "adoption": "Policy-sensitive", "valuation": "Mixed"},
        {"theme": "Cybersecurity", "adoption": "Steady budgets", "valuation": "Above median"},
        {"theme": "Nuclear and grid", "adoption": "Early project pipeline", "valuation": "Dispersed"},
        {"theme": "Digital payments", "adoption": "Mature in the US", "valuation": "Near median"},
    ])


def earnings_board() -> pd.DataFrame:
    return pd.DataFrame([
        {"symbol": "AAPL", "surprise_pct": 3.2, "guidance": "Maintained", "revision": 0.4},
        {"symbol": "MSFT", "surprise_pct": 1.1, "guidance": "Raised", "revision": 0.8},
        {"symbol": "NVDA", "surprise_pct": 4.5, "guidance": "Raised", "revision": 1.2},
        {"symbol": "JPM", "surprise_pct": -0.6, "guidance": "Maintained", "revision": -0.2},
        {"symbol": "XOM", "surprise_pct": 0.4, "guidance": "Cut", "revision": -0.5},
        {"symbol": "UNH", "surprise_pct": 1.8, "guidance": "Maintained", "revision": 0.1},
        {"symbol": "CAT", "surprise_pct": -1.4, "guidance": "Cut", "revision": -0.7},
    ])


def portfolio_history() -> pd.DataFrame:
    dates = [AS_OF - timedelta(days=20 - i) for i in range(21)]
    rng = _rng(25)
    equity = 1_000_000 * (1 + np.cumsum(rng.normal(0.0004, 0.006, len(dates))))
    benchmark = 1_000_000 * (1 + np.cumsum(rng.normal(0.0003, 0.005, len(dates))))
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1
    vol = pd.Series(equity).pct_change().rolling(5).std() * np.sqrt(252) * 100
    return pd.DataFrame({
        "date": dates,
        "portfolio": np.round(equity, 0),
        "benchmark": np.round(benchmark, 0),
        "drawdown_pct": np.round(drawdown * 100, 2),
        "vol_pct": np.round(vol.fillna(8), 2),
    })


def factor_exposures() -> pd.DataFrame:
    return pd.DataFrame([
        {"factor": "Market", "exposure": 0.92},
        {"factor": "Size", "exposure": -0.15},
        {"factor": "Value", "exposure": -0.22},
        {"factor": "Momentum", "exposure": 0.31},
        {"factor": "Quality", "exposure": 0.28},
        {"factor": "Low vol", "exposure": -0.05},
    ])


def stress_tests() -> pd.DataFrame:
    return pd.DataFrame([
        {"scenario": "Rates +100 bps", "pnl_pct": -4.8, "note": "Duration in TLT dominates"},
        {"scenario": "Equities -10%", "pnl_pct": -6.1, "note": "Equity beta, cash cushions"},
        {"scenario": "Oil +20%", "pnl_pct": 0.6, "note": "XOM offset by discretionary"},
        {"scenario": "USD +5%", "pnl_pct": -0.9, "note": "EEM and EURUSD"},
        {"scenario": "Credit spreads +150 bps", "pnl_pct": -2.4, "note": "Financials and TLT"},
    ])


def fund_quality() -> pd.DataFrame:
    return pd.DataFrame([
        {"fund": "TLT", "premium_pct": 0.02, "expense_pct": 0.15, "tracking_error": 0.08, "flow": "Inflow"},
        {"fund": "EEM", "premium_pct": -0.11, "expense_pct": 0.70, "tracking_error": 0.35, "flow": "Outflow"},
        {"fund": "IBIT", "premium_pct": 0.18, "expense_pct": 0.25, "tracking_error": 1.10, "flow": "Inflow"},
        {"fund": "GLD", "premium_pct": 0.04, "expense_pct": 0.40, "tracking_error": 0.12, "flow": "Flat"},
    ])


def category_history(category_id: int) -> pd.DataFrame:
    dates = _dates(12)
    base = 2 + (category_id % 5)
    values = np.round(base + np.cumsum(_rng(100 + category_id).normal(0, 0.15, len(dates))), 2)
    return pd.DataFrame({"date": dates, "value": values})


def reaction_path(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed % (2**32))
    dates = [AS_OF - timedelta(hours=8 - i) for i in range(8)]
    path = 100 * (1 + np.cumsum(rng.normal(0, 0.002, len(dates))))
    return pd.DataFrame({"time": dates, "index": np.round(path, 2)})
