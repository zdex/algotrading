"""
strategy/examples/ma_crossover_vectorised.py
--------------------------------------------
Vectorised dual SMA crossover — computes signals for ALL symbols
at once using pandas, instead of bar-by-bar Python loops.

10-100x faster than the event-driven version for backtesting
large universes (500+ symbols).

Architecture
------------
- Pre-compute phase : generate a full signals DataFrame offline
- Backtest phase    : replay signals through the engine as BarEvents arrive

This is the standard approach for large-universe backtesting.
Live trading still uses the event-driven bar-by-bar strategy.

Usage
-----
    strategy = VectorisedMACrossover(fast=10, slow=30)
    signals  = strategy.generate(prices_df)   # once, before the engine starts
    engine_strategy = strategy.to_event_strategy(signals, engine)
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from core.events import BarEvent, SignalDirection
from strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


# ── Signal generation (vectorised, offline) ───────────────────

@dataclass
class MACrossoverConfig:
    fast_period: int  = 10
    slow_period: int  = 30
    allow_short: bool = False


class VectorisedMACrossover:
    """
    Computes crossover signals for all symbols simultaneously.

    Input
    -----
    prices : pd.DataFrame
        Wide DataFrame — index=dates, columns=symbols, values=close prices.
        Produced by DataFeed.load_prices().

    Output
    ------
    signals : pd.DataFrame
        Same shape as prices.
        Values: "LONG" | "SHORT" | "FLAT" | "" (no change / still warming up)
    """

    def __init__(self, config: MACrossoverConfig = None):
        self.cfg = config or MACrossoverConfig()

    def generate(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        Main entry point. Returns signal DataFrame.
        """
        fast = self.cfg.fast_period
        slow = self.cfg.slow_period

        # Rolling SMAs — NaN during warm-up period
        fast_ma = prices.rolling(fast).mean()
        slow_ma = prices.rolling(slow).mean()

        # Shifted by 1 for previous bar comparison
        fast_prev = fast_ma.shift(1)
        slow_prev = slow_ma.shift(1)

        # Boolean masks — True where crossover occurs
        bull_cross = (fast_prev <= slow_prev) & (fast_ma > slow_ma)
        bear_cross = (fast_prev >= slow_prev) & (fast_ma < slow_ma)

        # Build signal DataFrame
        signals = pd.DataFrame("", index=prices.index, columns=prices.columns)
        signals[bull_cross] = "LONG"
        signals[bear_cross] = "SHORT" if self.cfg.allow_short else "FLAT"

        # Propagate position state forward (hold until next signal)
        signals = self._propagate(signals)

        logger.info(
            "Signals generated: %d dates × %d symbols | "
            "LONG=%d FLAT=%d SHORT=%d",
            len(signals), len(signals.columns),
            (signals == "LONG").sum().sum(),
            (signals == "FLAT").sum().sum(),
            (signals == "SHORT").sum().sum(),
        )
        return signals

    def _propagate(self, signals: pd.DataFrame) -> pd.DataFrame:
        """
        Forward-fill position state between signals.
        Empty string means 'no change' — fill with last known signal.
        Warm-up period (leading empty rows) stays empty.
        """
        return signals.replace("", pd.NA).ffill().fillna("")

    def signal_summary(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Per-symbol signal counts — useful for sanity checking."""
        empty = pd.DataFrame(
            columns=["long_days", "short_days", "flat_days", "total_trades"],
        ).rename_axis("symbol")
        if signals.empty or len(signals.columns) == 0:
            return empty

        rows = []
        for symbol in signals.columns:
            col = signals[symbol]
            rows.append({
                "symbol": symbol,
                "long_days":  (col == "LONG").sum(),
                "short_days": (col == "SHORT").sum(),
                "flat_days":  (col == "FLAT").sum(),
                "total_trades": (
                    (col != col.shift(1)) & (col != "")
                ).sum(),
            })
        return pd.DataFrame(rows).set_index("symbol")


# ── Event-driven adapter (plugs into the engine) ──────────────

class PrecomputedSignalStrategy(BaseStrategy):
    """
    Wraps a pre-computed signals DataFrame so it can be used
    inside the event-driven engine.

    On each BarEvent, looks up the pre-computed signal for that
    (symbol, date) and emits it if it has changed.
    """

    def __init__(
        self,
        signals: pd.DataFrame,
        symbols: list[str],
        engine=None,
    ):
        super().__init__(
            name    = "PrecomputedSignal",
            symbols = symbols,
            engine  = engine,
        )
        # Normalise index to date only for fast lookup
        self._signals = signals.copy()
        self._signals.index = pd.to_datetime(self._signals.index).normalize()
        self._last_signal: dict[str, str] = {}

    def calculate(self, event: BarEvent) -> None:
        symbol = event.symbol
        date   = pd.Timestamp(event.timestamp).normalize()

        if date not in self._signals.index:
            return
        if symbol not in self._signals.columns:
            return

        new_sig = self._signals.at[date, symbol]
        if not new_sig or new_sig == self._last_signal.get(symbol):
            return   # no change

        direction_map = {
            "LONG":  SignalDirection.LONG,
            "SHORT": SignalDirection.SHORT,
            "FLAT":  SignalDirection.FLAT,
        }
        direction = direction_map.get(new_sig)
        if direction is None:
            return

        logger.debug("%s → %s on %s", symbol, new_sig, date.date())
        self.emit_signal(symbol, direction, strength=1.0)
        self._last_signal[symbol] = new_sig
