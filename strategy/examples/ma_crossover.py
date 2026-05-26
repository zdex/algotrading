"""
strategy/examples/ma_crossover.py
----------------------------------
Classic dual moving-average crossover strategy.

Logic
-----
- Fast MA crosses ABOVE slow MA  →  go LONG
- Fast MA crosses BELOW slow MA  →  go FLAT (exit)

Optionally add a short leg when the fast MA crosses below.
"""

import logging
from typing import Optional

from core.events import BarEvent, SignalDirection
from strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class MACrossoverStrategy(BaseStrategy):
    """
    Dual SMA crossover strategy.

    Parameters
    ----------
    fast_period : int   window for the fast moving average (default 10)
    slow_period : int   window for the slow moving average (default 30)
    allow_short : bool  emit SHORT signal on bearish cross (default False)
    """

    def __init__(
        self,
        symbols:     list,
        fast_period: int  = 10,
        slow_period: int  = 30,
        allow_short: bool = False,
        engine=None,
    ):
        super().__init__(
            name   = f"MA_Cross_{fast_period}_{slow_period}",
            symbols= symbols,
            engine = engine,
        )
        assert fast_period < slow_period, "fast_period must be < slow_period"
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.allow_short = allow_short

        # Track current position direction per symbol to avoid repeat signals
        self._position: dict[str, SignalDirection] = {}

    # ── Strategy logic ────────────────────────────────────────

    def calculate(self, event: BarEvent) -> None:
        symbol = event.symbol
        n      = self.bar_count(symbol)

        # Need enough bars for the slow MA
        if n < self.slow_period:
            logger.debug(
                "%s: warming up (%d / %d bars)", symbol, n, self.slow_period
            )
            return

        closes    = [b.close for b in self._bars[symbol]]
        fast_ma   = _sma(closes, self.fast_period)
        slow_ma   = _sma(closes, self.slow_period)

        # Previous values (one bar ago)
        fast_prev = _sma(closes[:-1], self.fast_period)
        slow_prev = _sma(closes[:-1], self.slow_period)

        current_pos = self._position.get(symbol, SignalDirection.FLAT)

        # ── Bullish cross ──────────────────────────────────────
        if fast_prev <= slow_prev and fast_ma > slow_ma:
            if current_pos != SignalDirection.LONG:
                logger.info(
                    "%s LONG signal | fast_ma=%.4f slow_ma=%.4f close=%.4f",
                    symbol, fast_ma, slow_ma, event.close,
                )
                self.emit_signal(symbol, SignalDirection.LONG, strength=1.0)
                self._position[symbol] = SignalDirection.LONG

        # ── Bearish cross ──────────────────────────────────────
        elif fast_prev >= slow_prev and fast_ma < slow_ma:
            if current_pos == SignalDirection.LONG:
                logger.info(
                    "%s FLAT signal (exit long) | fast_ma=%.4f slow_ma=%.4f",
                    symbol, fast_ma, slow_ma,
                )
                self.emit_signal(symbol, SignalDirection.FLAT)
                self._position[symbol] = SignalDirection.FLAT

            if self.allow_short and current_pos != SignalDirection.SHORT:
                logger.info(
                    "%s SHORT signal | fast_ma=%.4f slow_ma=%.4f close=%.4f",
                    symbol, fast_ma, slow_ma, event.close,
                )
                self.emit_signal(symbol, SignalDirection.SHORT, strength=1.0)
                self._position[symbol] = SignalDirection.SHORT


# ── Utility ───────────────────────────────────────────────────

def _sma(values: list, period: int) -> Optional[float]:
    """Simple moving average of the last `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period
