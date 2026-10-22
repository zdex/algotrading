"""Chart tables for Market Monitor panels. All series are simulated."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from market_monitor.catalog import AS_OF

_RNG = np.random.default_rng(20)


def _dates(n: int = 18) -> list[datetime]:
    start = AS_OF - timedelta(days=30 * (n - 1))
    return [start + timedelta(days=30 * i) for i in range(n)]


def macro_surprise() -> pd.DataFrame:
    countries = ["United States", "Euro area", "United Kingdom", "Japan", "China", "India"]
    indicators = ["CPI", "Core CPI", "Payrolls", "PMI", "Retail sales", "GDP"]
    rows = []
    for country in countries:
        for index, indicator in enumerate(indicators):
            yoy = round(float(_RNG.normal(0, 0.6)), 2)
            mom = round(yoy / 3 + float(_RNG.normal(0, 0.15)), 2)
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
    frame = pd.DataFrame({
        "date": dates,
        "policy_rate": [4.50, 4.50, 4.25, 4.25, 4.00, 4.00, 3.75, 3.75],
        "futures_implied": [4.48, 4.42, 4.20, 4.05, 3.90, 3.82, 3.70, 3.60],
    })
    return frame


def yield_curve() -> pd.DataFrame:
    return pd.DataFrame({
        "tenor": ["1M", "3M", "2Y", "5Y", "10Y", "30Y"],
        "yield_pct": [4.15, 4.05, 3.72, 3.68, 3.95, 4.22],
    })


def regional_scorecard() -> pd.DataFrame:
    return pd.DataFrame([
        {"region": "United States", "growth": "Slowing, still positive", "inflation": "Near 2%", "policy": "Easing bias", "watch": "Labor revisions"},
        {"region": "Euro area", "growth": "Soft", "inflation": "Close to target", "policy": "On hold", "watch": "Energy"},
        {"region": "China", "growth": "Uneven", "inflation": "Low", "policy": "Targeted support", "watch": "Property"},
        {"region": "India", "growth": "Firm", "inflation": "Contained", "policy": "Meeting ahead", "watch": "Local flows"},
        {"region": "Japan", "growth": "Modest", "inflation": "Around 2%", "policy": "Normalization", "watch": "Yen"},
    ])


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
    return pd.DataFrame({
        "date": dates,
        "conditions_index": np.round(np.linspace(-0.4, 0.3, len(dates)) + _RNG.normal(0, 0.05, len(dates)), 2),
    })


def breadth() -> pd.DataFrame:
    dates = _dates(12)
    return pd.DataFrame({
        "date": dates,
        "pct_above_200d": np.clip(np.round(62 + _RNG.normal(0, 4, len(dates)), 1), 20, 90),
        "advance_decline": np.round(_RNG.normal(0.1, 0.4, len(dates)), 2),
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
    return pd.DataFrame({
        "date": dates,
        "ig_bps": np.round(95 + _RNG.normal(0, 2, len(dates)).cumsum() * 0.3, 1),
        "hy_bps": np.round(320 + _RNG.normal(0, 4, len(dates)).cumsum() * 0.4, 1),
    })


def sector_performance() -> pd.DataFrame:
    sectors = [
        "Information Technology", "Financials", "Health Care", "Energy", "Industrials",
        "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
        "Real Estate", "Communication Services",
    ]
    rows = []
    for sector in sectors:
        base = float(_RNG.normal(0, 1.2))
        rows.append({
            "sector": sector,
            "1W": round(base * 0.4, 2),
            "1M": round(base, 2),
            "3M": round(base * 2.1, 2),
            "1Y": round(base * 4.0, 2),
            "revision": round(float(_RNG.normal(0, 0.4)), 2),
            "valuation_percentile": int(np.clip(50 + _RNG.normal(0, 18), 5, 95)),
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
    equity = 1_000_000 * (1 + np.cumsum(_RNG.normal(0.0004, 0.006, len(dates))))
    benchmark = 1_000_000 * (1 + np.cumsum(_RNG.normal(0.0003, 0.005, len(dates))))
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
    values = np.round(base + np.cumsum(_RNG.normal(0, 0.15, len(dates))), 2)
    return pd.DataFrame({"date": dates, "value": values})


def reaction_path(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed % (2**32))
    dates = [AS_OF - timedelta(hours=8 - i) for i in range(8)]
    path = 100 * (1 + np.cumsum(rng.normal(0, 0.002, len(dates))))
    return pd.DataFrame({"time": dates, "index": np.round(path, 2)})
