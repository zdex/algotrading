"""
core/risk.py
------------
Pre-trade risk gate.  Sits between SignalEvent and OrderEvent.
Converts a sized signal into an approved OrderEvent, or drops it.
"""

import logging
import uuid
from dataclasses import dataclass

from core.events import (
    SignalEvent, OrderEvent, OrderSide, OrderType,
    SignalDirection, EventType,
)
from core.portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_position_pct:   float = 0.10   # max % of equity per symbol
    max_open_positions: int   = 10
    max_drawdown_pct:   float = 0.20   # halt if equity drops 20%
    default_order_pct:  float = 0.05   # default sizing: 5% of equity


class RiskManager:
    """
    Converts SignalEvents → OrderEvents after risk checks.

    Checks performed
    ----------------
    1. Drawdown halt — stops all trading if equity loss exceeds threshold
    2. Position count  — rejects new entries if too many open positions
    3. Position sizing — sizes order as % of equity, capped per symbol
    """

    def __init__(
        self,
        portfolio: Portfolio,
        engine,                  # EventEngine (injected to emit OrderEvents)
        config: RiskConfig = None,
        current_prices: dict = None,
    ):
        self.portfolio = portfolio
        self.engine    = engine
        self.cfg       = config or RiskConfig()
        self.prices    = current_prices or {}   # updated externally on each bar
        self._halted   = False

    # ── Price updates ─────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price

    # ── Event handler ─────────────────────────────────────────

    def on_signal(self, event: SignalEvent) -> None:
        """Called by engine on every SignalEvent."""
        if self._halted:
            logger.warning("RISK HALT active — signal for %s rejected.", event.symbol)
            return

        equity = self.portfolio.total_equity(self.prices)

        # 1. Drawdown check
        dd = 1 - equity / self.portfolio.initial_cash
        if dd >= self.cfg.max_drawdown_pct:
            logger.error(
                "HALT triggered! Drawdown %.1f%% ≥ limit %.1f%%",
                dd * 100, self.cfg.max_drawdown_pct * 100,
            )
            self._halted = True
            return

        # 2. Flat signal → close position
        if event.direction == SignalDirection.FLAT:
            self._close_position(event.symbol)
            return

        # 3. Position count check
        open_positions = sum(
            1 for p in self.portfolio.positions.values() if p.quantity != 0
        )
        symbol_has_position = (
            event.symbol in self.portfolio.positions
            and self.portfolio.positions[event.symbol].quantity != 0
        )
        if open_positions >= self.cfg.max_open_positions and not symbol_has_position:
            logger.warning("Position limit reached — signal for %s rejected.", event.symbol)
            return

        # 4. Size the order
        price    = self.prices.get(event.symbol)
        if not price:
            logger.warning("No price for %s — cannot size order.", event.symbol)
            return

        alloc    = equity * self.cfg.default_order_pct * event.strength
        max_alloc= equity * self.cfg.max_position_pct
        alloc    = min(alloc, max_alloc)
        quantity = alloc / price

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
            "RISK APPROVED: %s %s x%.4f (alloc=%.2f)",
            side.value, event.symbol, quantity, alloc,
        )
        self.engine.put(order)

    # ── Helpers ───────────────────────────────────────────────

    def _close_position(self, symbol: str) -> None:
        pos = self.portfolio.positions.get(symbol)
        if not pos or pos.quantity == 0:
            return

        side     = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        quantity = abs(pos.quantity)
        order    = OrderEvent(
            symbol     = symbol,
            side       = side,
            order_type = OrderType.MARKET,
            quantity   = quantity,
            order_id   = str(uuid.uuid4())[:8],
        )
        logger.info("CLOSING position in %s: %s x%.4f", symbol, side.value, quantity)
        self.engine.put(order)

    def reset_halt(self) -> None:
        """Manually clear a risk halt (for testing/ops)."""
        self._halted = False
        logger.info("Risk halt cleared manually.")
