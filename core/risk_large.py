"""
core/risk_large.py
------------------
Portfolio-level risk manager for large universes (100–600 symbols).

Extends base RiskManager with:
- Sector concentration limits
- Correlation-based position rejection
- Tighter per-symbol sizing
- Portfolio heat / gross exposure cap
- Dynamic position sizing (volatility-adjusted)

Usage
-----
    from core.risk_large import LargeUniverseRiskManager, LargeUniverseRiskConfig

    risk = LargeUniverseRiskManager(
        portfolio    = portfolio,
        engine       = engine,
        sector_map   = get_sp500_sector_map(),
        prices_df    = feed.load_prices(symbols),
        config       = LargeUniverseRiskConfig(),
    )
    engine.register(EventType.SIGNAL, risk.on_signal)
"""

import logging
import uuid
from dataclasses import dataclass, field

import pandas as pd

from core.events import (
    SignalEvent, OrderEvent, OrderSide, OrderType, SignalDirection,
)
from core.portfolio import Portfolio

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────

@dataclass
class LargeUniverseRiskConfig:
    # Per-symbol limits
    max_position_pct:   float = 0.02     # max 2% of equity per symbol
    default_order_pct:  float = 0.01     # default sizing: 1% of equity

    # Portfolio-level limits
    max_open_positions: int   = 50       # max concurrent holdings
    max_gross_exposure: float = 1.0      # max 100% of equity deployed
    max_drawdown_pct:   float = 0.20     # halt if equity drops 20%

    # Sector limits
    max_sector_pct:     float = 0.25     # max 25% of equity in one sector

    # Correlation filter
    max_correlation:    float = 0.85     # reject if corr with existing > 0.85
    corr_lookback:      int   = 60       # days for correlation calculation

    # Volatility targeting
    use_vol_targeting:  bool  = True     # scale size by inverse volatility
    target_annual_vol:  float = 0.15     # target 15% annualised vol per position
    vol_lookback:       int   = 20       # days for vol estimate


# ── Risk Manager ──────────────────────────────────────────────

class LargeUniverseRiskManager:

    def __init__(
        self,
        portfolio:  Portfolio,
        engine,
        sector_map: dict[str, str] = None,    # {symbol: sector}
        prices_df:  pd.DataFrame   = None,    # wide close prices for corr/vol
        config:     LargeUniverseRiskConfig = None,
    ):
        self.portfolio  = portfolio
        self.engine     = engine
        self.sector_map = sector_map or {}
        self.prices_df  = prices_df            # updated periodically
        self.cfg        = config or LargeUniverseRiskConfig()
        self._halted    = False
        self._prices: dict[str, float] = {}    # latest bar prices

    # ── Price updates ─────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    # ── Main handler ──────────────────────────────────────────

    def on_signal(self, event: SignalEvent) -> None:
        if self._halted:
            logger.warning("RISK HALT — signal for %s rejected.", event.symbol)
            return

        equity = self.portfolio.total_equity(self._prices)

        # ── 1. Drawdown halt ──────────────────────────────────
        dd = 1 - equity / self.portfolio.initial_cash
        if dd >= self.cfg.max_drawdown_pct:
            logger.error("HALT! Drawdown %.1f%% ≥ limit.", dd * 100)
            self._halted = True
            return

        # ── 2. Exit signals bypass most checks ────────────────
        if event.direction == SignalDirection.FLAT:
            self._close_position(event.symbol)
            return

        # ── 3. Portfolio heat check ───────────────────────────
        gross_exposure = self._gross_exposure(equity)
        if gross_exposure >= self.cfg.max_gross_exposure:
            logger.debug(
                "Gross exposure %.1f%% at cap — %s rejected.",
                gross_exposure * 100, event.symbol,
            )
            return

        # ── 4. Open position count ────────────────────────────
        open_count = sum(
            1 for p in self.portfolio.positions.values() if p.quantity != 0
        )
        already_open = (
            event.symbol in self.portfolio.positions
            and self.portfolio.positions[event.symbol].quantity != 0
        )
        if open_count >= self.cfg.max_open_positions and not already_open:
            logger.debug("Position limit %d reached.", self.cfg.max_open_positions)
            return

        # ── 5. Sector concentration ───────────────────────────
        if not self._sector_check(event.symbol, equity):
            return

        # ── 6. Correlation filter ─────────────────────────────
        if not self._correlation_check(event.symbol):
            return

        # ── 7. Sizing ─────────────────────────────────────────
        price = self._prices.get(event.symbol)
        if not price:
            logger.warning("No price for %s.", event.symbol)
            return

        quantity = self._size_position(event.symbol, equity, price, event.strength)
        if quantity <= 0:
            return

        side = (
            OrderSide.BUY
            if event.direction == SignalDirection.LONG
            else OrderSide.SELL
        )

        order = OrderEvent(
            symbol     = event.symbol,
            side       = side,
            order_type = OrderType.MARKET,
            quantity   = round(quantity, 6),
            order_id   = str(uuid.uuid4())[:8],
        )
        logger.info(
            "APPROVED %s %s x%.4f @ %.2f",
            side.value, event.symbol, quantity, price,
        )
        self.engine.put(order)

    # ── Sizing ────────────────────────────────────────────────

    def _size_position(
        self,
        symbol:   str,
        equity:   float,
        price:    float,
        strength: float,
    ) -> float:
        """
        Volatility-targeted position sizing.

        If use_vol_targeting=True:
            quantity = (equity × target_vol) / (annual_vol × price)
        Else:
            quantity = (equity × default_order_pct × strength) / price

        Always capped at max_position_pct of equity.
        """
        max_notional = equity * self.cfg.max_position_pct

        if self.cfg.use_vol_targeting and self.prices_df is not None:
            vol = self._annual_vol(symbol)
            if vol and vol > 0:
                notional = equity * self.cfg.target_annual_vol / vol
            else:
                notional = equity * self.cfg.default_order_pct
        else:
            notional = equity * self.cfg.default_order_pct * strength

        notional = min(notional, max_notional)
        return notional / price

    def _annual_vol(self, symbol: str) -> float | None:
        """Estimate annualised volatility from recent returns."""
        if self.prices_df is None or symbol not in self.prices_df.columns:
            return None
        series  = self.prices_df[symbol].dropna().tail(self.cfg.vol_lookback + 1)
        returns = series.pct_change().dropna()
        if len(returns) < 5:
            return None
        return float(returns.std() * (252 ** 0.5))

    # ── Sector check ──────────────────────────────────────────

    def _sector_check(self, symbol: str, equity: float) -> bool:
        """Reject if adding this position would breach sector cap."""
        sector = self.sector_map.get(symbol)
        if not sector:
            return True   # unknown sector — allow

        sector_symbols = [
            s for s, sec in self.sector_map.items() if sec == sector
        ]
        sector_value = sum(
            self.portfolio.positions[s].market_value(
                self._prices.get(s, self.portfolio.positions[s].avg_price)
            )
            for s in sector_symbols
            if s in self.portfolio.positions
        )
        sector_pct = sector_value / equity if equity else 0

        if sector_pct >= self.cfg.max_sector_pct:
            logger.debug(
                "Sector '%s' at %.1f%% cap — %s rejected.",
                sector, sector_pct * 100, symbol,
            )
            return False
        return True

    # ── Correlation check ─────────────────────────────────────

    def _correlation_check(self, symbol: str) -> bool:
        """
        Reject if symbol is too correlated with any existing position.
        Uses pre-loaded prices_df for speed.
        """
        if self.prices_df is None or symbol not in self.prices_df.columns:
            return True   # can't check — allow

        open_symbols = [
            s for s, p in self.portfolio.positions.items()
            if p.quantity != 0 and s in self.prices_df.columns
        ]
        if not open_symbols:
            return True

        lookback = self.cfg.corr_lookback
        window   = self.prices_df[open_symbols + [symbol]].tail(lookback + 1)
        returns  = window.pct_change().dropna()

        if len(returns) < 10:
            return True

        corr_matrix = returns.corr()
        if symbol not in corr_matrix.columns:
            return True

        max_corr = corr_matrix[symbol].drop(symbol).abs().max()
        if max_corr >= self.cfg.max_correlation:
            logger.debug(
                "%s rejected: max correlation %.2f ≥ limit %.2f",
                symbol, max_corr, self.cfg.max_correlation,
            )
            return False
        return True

    # ── Helpers ───────────────────────────────────────────────

    def _gross_exposure(self, equity: float) -> float:
        total_mv = sum(
            abs(p.market_value(
                self._prices.get(s, p.avg_price)
            ))
            for s, p in self.portfolio.positions.items()
        )
        return total_mv / equity if equity else 0

    def _close_position(self, symbol: str) -> None:
        pos = self.portfolio.positions.get(symbol)
        if not pos or pos.quantity == 0:
            return
        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        order = OrderEvent(
            symbol     = symbol,
            side       = side,
            order_type = OrderType.MARKET,
            quantity   = abs(pos.quantity),
            order_id   = str(uuid.uuid4())[:8],
        )
        logger.info("CLOSE %s %s", symbol, side.value)
        self.engine.put(order)

    def portfolio_snapshot(self) -> dict:
        """Summary of current portfolio state for monitoring."""
        equity = self.portfolio.total_equity(self._prices)

        sector_exposure: dict[str, float] = {}
        for s, p in self.portfolio.positions.items():
            if p.quantity == 0:
                continue
            sector = self.sector_map.get(s, "Unknown")
            mv     = p.market_value(self._prices.get(s, p.avg_price))
            sector_exposure[sector] = sector_exposure.get(sector, 0) + mv

        return {
            "equity":           round(equity, 2),
            "gross_exposure":   round(self._gross_exposure(equity), 4),
            "open_positions":   sum(1 for p in self.portfolio.positions.values() if p.quantity != 0),
            "halted":           self._halted,
            "sector_exposure":  {
                k: round(v / equity, 4) for k, v in sector_exposure.items()
            },
        }

    def reset_halt(self) -> None:
        self._halted = False
        logger.info("Risk halt cleared.")
