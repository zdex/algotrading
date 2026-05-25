"""
strategy/base.py
----------------
Abstract base class every strategy must implement.

Strategies
- receive BarEvents (and optionally TickEvents)
- emit SignalEvents via self.emit_signal()
- hold NO position state (that lives in Portfolio)
- hold NO order state (that lives in OrderManager / Broker)
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional

import pandas as pd

from core.events import BarEvent, SignalEvent, SignalDirection


class BaseStrategy(ABC):
    """
    Inherit from this and implement on_bar().

    Attributes
    ----------
    name        : human-readable strategy identifier
    symbols     : list of symbols this strategy trades
    engine      : injected EventEngine reference
    _bars       : dict[symbol → list[BarEvent]], rolling history
    """

    def __init__(self, name: str, symbols: list, engine=None):
        self.name    = name
        self.symbols = symbols
        self.engine  = engine                          # set after construction
        self._bars: dict[str, list[BarEvent]] = defaultdict(list)

    # ── Lifecycle ─────────────────────────────────────────────

    def set_engine(self, engine) -> None:
        """Inject the engine after construction."""
        self.engine = engine

    def on_start(self) -> None:
        """Called once before the first bar. Override for init logic."""

    def on_stop(self) -> None:
        """Called once after the last bar. Override for cleanup."""

    # ── Core interface ────────────────────────────────────────

    def on_bar(self, event: BarEvent) -> None:
        """
        Entry point for every bar.  Stores the bar then calls
        calculate() so subclasses only have to implement logic.
        """
        if event.symbol not in self.symbols:
            return
        self._bars[event.symbol].append(event)
        self.calculate(event)

    @abstractmethod
    def calculate(self, event: BarEvent) -> None:
        """
        Implement your signal logic here.
        Call self.emit_signal() to generate trading signals.
        """
        a = 10
        raise NotImplementedError

    # ── Helpers ───────────────────────────────────────────────

    def emit_signal(
        self,
        symbol: str,
        direction: SignalDirection,
        strength: float = 1.0,
    ) -> None:
        """Push a SignalEvent onto the engine queue."""
        if self.engine is None:
            raise RuntimeError("Strategy has no engine attached. Call set_engine().")
        signal = SignalEvent(
            symbol    = symbol,
            direction = direction,
            strength  = max(0.0, min(1.0, strength)),
            strategy  = self.name,
        )
        self.engine.put(signal)

    def bars_df(self, symbol: str) -> pd.DataFrame:
        """Return stored bars as a DataFrame (OHLCV columns)."""
        rows = [
            {
                "timestamp": b.timestamp,
                "open":  b.open,
                "high":  b.high,
                "low":   b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in self._bars[symbol]
        ]
        df = pd.DataFrame(rows)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
        return df

    def bar_count(self, symbol: str) -> int:
        return len(self._bars[symbol])

    def last_close(self, symbol: str) -> Optional[float]:
        bars = self._bars.get(symbol)
        return bars[-1].close if bars else None
