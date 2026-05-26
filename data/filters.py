"""
data/filters.py
---------------
Pre-trade universe filters applied before strategy execution.

Filters
-------
- Liquidity  : average daily dollar volume ≥ threshold
- Price      : minimum close price (removes penny stocks)
- History    : minimum number of trading days available
- Volatility : optional — remove extremely volatile names

Usage
-----
    from data.filters import LiquidityFilter
    filt   = LiquidityFilter(feed)
    liquid = filt.apply(symbols)
    print(f"{len(liquid)} / {len(symbols)} symbols passed.")
"""

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    min_adv_usd:      float = 1_000_000   # $1M average daily dollar volume
    min_price:        float = 5.0          # exclude penny stocks < $5
    min_history_days: int   = 252          # at least 1 year of data
    adv_lookback:     int   = 20           # days used to compute ADV
    max_daily_return: float = 0.50         # exclude if any day moved >50% (data error)


class LiquidityFilter:
    """
    Filters a symbol universe down to liquid, clean symbols.

    Parameters
    ----------
    feed : DataFeed  — used to load OHLCV per symbol
    config : FilterConfig
    """

    def __init__(self, feed, config: FilterConfig = None):
        self.feed   = feed
        self.cfg    = config or FilterConfig()
        self._log: dict[str, str] = {}    # symbol → rejection reason

    def apply(self, symbols: list[str]) -> list[str]:
        """
        Returns the subset of symbols that pass all filters.
        Populates self._log with rejection reasons.
        """
        passed, rejected = [], []

        for symbol in symbols:
            reason = self._check(symbol)
            if reason is None:
                passed.append(symbol)
            else:
                rejected.append(symbol)
                self._log[symbol] = reason

        logger.info(
            "Liquidity filter: %d passed, %d rejected from %d total.",
            len(passed), len(rejected), len(symbols),
        )
        return passed

    def rejection_log(self) -> pd.DataFrame:
        """Returns a DataFrame of rejected symbols and their reasons."""
        return pd.DataFrame(
            list(self._log.items()), columns=["symbol", "reason"]
        ).sort_values("reason")

    # ── Per-symbol checks ─────────────────────────────────────

    def _check(self, symbol: str) -> str | None:
        """Returns rejection reason string, or None if symbol passes."""
        df = self.feed.load_ohlcv(symbol)

        # 1. Data availability
        if df is None or df.empty:
            return "no_data"

        if len(df) < self.cfg.min_history_days:
            return f"insufficient_history ({len(df)} days)"

        # 2. Price filter
        recent_close = df["close"].iloc[-1]
        if recent_close < self.cfg.min_price:
            return f"price_too_low ({recent_close:.2f})"

        # 3. Liquidity: Average Daily Dollar Volume
        recent = df.tail(self.cfg.adv_lookback)
        adv    = (recent["close"] * recent["volume"]).mean()
        if adv < self.cfg.min_adv_usd:
            return f"illiquid (ADV=${adv:,.0f})"

        # 4. Data quality: extreme single-day moves
        returns = df["close"].pct_change().abs()
        if (returns > self.cfg.max_daily_return).any():
            return "extreme_move (possible data error)"

        return None   # passed all checks
