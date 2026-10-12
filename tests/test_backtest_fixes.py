"""
Regression tests for the backtest correctness fixes.

    pytest -q
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import EventEngine
from core.events import (
    BarEvent, EventType, FillEvent, OrderEvent, OrderSide, SignalDirection, SignalEvent,
)
from core.portfolio import Portfolio
from core.risk_large import LargeUniverseRiskConfig, LargeUniverseRiskManager
from backtester.metrics import performance_report
from data.feed import DataFeed
from data.filters import FilterConfig, LiquidityFilter
from execution.adapters.simulated import SimConfig, SimulatedBroker


def fill(symbol, side, qty, price, ts, commission=1.0):
    return FillEvent(symbol=symbol, side=side, quantity=qty, fill_price=price,
                     commission=commission, order_id="x", timestamp=ts)


def bar(symbol, ts, o, c):
    return BarEvent(timestamp=ts, symbol=symbol, open=o, high=max(o, c), low=min(o, c),
                    close=c, volume=1e6)


# ── Portfolio trade ledger ────────────────────────────────────

def test_trade_ledger_matches_by_symbol_not_fill_order():
    p = Portfolio(initial_cash=100_000)
    d1, d2, d3 = datetime(2021, 1, 4), datetime(2021, 1, 5), datetime(2021, 1, 6)
    # Interleaved fills across two symbols — the old fills[i]/fills[i+1] pairing breaks here
    p.on_fill(fill("AAA", OrderSide.BUY, 10, 100, d1))
    p.on_fill(fill("BBB", OrderSide.BUY, 5, 50, d1))
    p.on_fill(fill("AAA", OrderSide.SELL, 10, 110, d2))
    p.on_fill(fill("BBB", OrderSide.SELL, 5, 40, d3))
    assert [t.symbol for t in p.trades] == ["AAA", "BBB"]
    assert p.trades[0].gross_pnl == pytest.approx(100)
    assert p.trades[1].gross_pnl == pytest.approx(-50)
    assert p.trades[0].net_pnl == pytest.approx(98)       # two $1 commissions
    assert p.trades[0].entry_time == d1 and p.trades[0].exit_time == d2


def test_reversal_resets_average_price():
    p = Portfolio(initial_cash=100_000)
    p.on_fill(fill("AAA", OrderSide.BUY, 10, 100, datetime(2021, 1, 4)))
    p.on_fill(fill("AAA", OrderSide.SELL, 15, 120, datetime(2021, 1, 5)))
    pos = p.positions["AAA"]
    assert pos.quantity == pytest.approx(-5)
    assert pos.avg_price == pytest.approx(120)
    assert p.trades[0].quantity == pytest.approx(10)
    assert p.trades[0].gross_pnl == pytest.approx(200)


# ── Simulated broker: next-open fills ─────────────────────────

def test_broker_fills_at_next_bar_open_with_bar_timestamp():
    engine = EventEngine()
    broker = SimulatedBroker(engine, SimConfig(slippage_bps=0, commission_per_trade=0))
    fills = []
    engine.register(EventType.BAR, broker.on_bar)
    engine.register(EventType.ORDER, broker.on_order)
    engine.register(EventType.FILL, fills.append)

    d1, d2 = datetime(2021, 1, 4), datetime(2021, 1, 5)

    def on_bar(e):
        if e.timestamp == d1:
            engine.put(OrderEvent(symbol="AAA", side=OrderSide.BUY, quantity=1,
                                  order_id="o1", timestamp=d1))
    engine.register(EventType.BAR, on_bar)

    engine.start(iter([bar("AAA", d1, 100, 101), bar("AAA", d2, 105, 106)]))
    assert len(fills) == 1
    assert fills[0].fill_price == pytest.approx(105)    # next bar's open, not 101
    assert fills[0].timestamp == d2


def test_broker_legacy_wiring_still_fills():
    engine = EventEngine()
    broker = SimulatedBroker(engine, SimConfig(slippage_bps=0))
    fills = []
    engine.register(EventType.FILL, fills.append)
    broker.update_price("AAA", 50.0)
    broker.on_order(OrderEvent(symbol="AAA", side=OrderSide.BUY, quantity=1, order_id="o"))
    engine.start(iter([]))
    while not engine._queue.empty():
        fills.append(engine._queue.get())
    assert fills and fills[0].fill_price == pytest.approx(50.0)


# ── Risk manager ──────────────────────────────────────────────

def _prices(n=300, cols=("AAA", "BBB", "CCC"), seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    data = {c: 100 * np.exp(np.cumsum(rng.normal(0, 0.01 * (i + 1), n))) for i, c in enumerate(cols)}
    return pd.DataFrame(data, index=idx)


def test_volatility_is_point_in_time():
    prices = _prices()
    # Make the last 30 days wildly volatile: a point-in-time estimate earlier must ignore it
    prices.iloc[-30:, 0] *= np.exp(np.random.default_rng(2).normal(0, 0.2, 30))
    risk = LargeUniverseRiskManager(Portfolio(1e6), EventEngine(), prices_df=prices)
    ts = prices.index[100]
    expected = prices["AAA"].pct_change().iloc[100 - 19:101].std() * np.sqrt(252)
    assert risk._annual_vol("AAA", ts) == pytest.approx(expected)
    assert risk._annual_vol("AAA", ts) < risk._annual_vol("AAA", prices.index[-1])


def test_pending_orders_count_toward_position_limit():
    prices = _prices(cols=tuple(f"S{i}" for i in range(5)))
    engine = EventEngine()
    cfg = LargeUniverseRiskConfig(max_open_positions=2, max_correlation=1.01)
    risk = LargeUniverseRiskManager(Portfolio(1e6), engine, prices_df=prices, config=cfg)
    ts = prices.index[200].to_pydatetime()
    for s in prices.columns:
        risk.update_price(s, float(prices[s].iloc[200]))
    for s in prices.columns:   # five LONG signals on the same day, none filled yet
        risk.on_signal(SignalEvent(symbol=s, direction=SignalDirection.LONG, timestamp=ts))
    approved = [d for d in risk.decisions if d["action"] == "approved"]
    rejected = [d for d in risk.decisions if d["check"] == "max_open_positions"]
    assert len(approved) == 2 and len(rejected) == 3


def test_portfolio_vol_target_mode_sizes_by_volatility():
    prices = _prices()
    risk = LargeUniverseRiskManager(Portfolio(1e6), EventEngine(), prices_df=prices,
                                    config=LargeUniverseRiskConfig(max_open_positions=50))
    ts = prices.index[-1]
    w_low = risk.target_notional("AAA", 1e6, 1.0, ts) / 1e6    # lowest-vol column
    w_high = risk.target_notional("CCC", 1e6, 1.0, ts) / 1e6
    assert w_high < w_low <= 0.02


# ── Liquidity filter ──────────────────────────────────────────

def test_liquidity_filter_uses_only_data_before_as_of(tmp_path):
    idx = pd.bdate_range("2020-01-01", periods=400)
    price = np.r_[np.full(300, 2.0), np.geomspace(2.0, 50.0, 100)]   # penny stock that later re-rates
    df = pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                       "volume": np.full(400, 1e7)}, index=idx)
    df.index.name = "timestamp"
    feed = DataFeed(cache_dir=str(tmp_path))
    feed._save("PNY", df)
    filt = LiquidityFilter(feed, FilterConfig(min_history_days=100, min_adv_usd=1e6))
    assert filt.apply(["PNY"]) == ["PNY"]                     # look-ahead: passes
    assert filt.apply(["PNY"], as_of=str(idx[300].date())) == []   # as of then: too cheap


# ── Metrics ───────────────────────────────────────────────────

def test_performance_report_uses_calendar_time():
    idx = pd.bdate_range("2021-01-01", "2024-01-01", inclusive="left")
    equity = pd.Series(np.linspace(1e6, 1.331e6, len(idx)), index=idx)
    rep = performance_report(equity, [10, -5])
    assert rep["total_return_pct"] == pytest.approx(33.1, abs=0.1)
    assert 9.0 < rep["cagr_pct"] < 11.0     # ~10% a year over 3 years
