"""
core/portfolio.py
-----------------
Tracks positions, cash, and P&L in real time.
Updated exclusively by FillEvents from the broker.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from core.events import FillEvent, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol:     str
    quantity:   float = 0.0       # positive = long, negative = short
    avg_price:  float = 0.0
    realised_pnl: float = 0.0

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def unrealised_pnl(self, current_price: float) -> float:
        return self.quantity * (current_price - self.avg_price)

    def update(self, fill: FillEvent) -> None:
        """Update position after a fill."""
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity

        if self.quantity == 0:
            self.avg_price = fill.fill_price
        elif (self.quantity > 0) == (signed_qty > 0):
            # Adding to existing position — recalculate avg
            total_cost  = self.avg_price * self.quantity + fill.fill_price * signed_qty
            self.quantity += signed_qty
            self.avg_price = total_cost / self.quantity if self.quantity else 0
            return
        else:
            # Reducing or reversing
            closed_qty = min(abs(self.quantity), abs(signed_qty))
            pnl = closed_qty * (fill.fill_price - self.avg_price)
            if self.quantity < 0:
                pnl = -pnl
            self.realised_pnl += pnl

        self.quantity += signed_qty
        if self.quantity == 0:
            self.avg_price = 0.0


@dataclass
class Portfolio:
    initial_cash: float = 100_000.0
    cash: float = field(init=False)
    positions: Dict[str, Position] = field(default_factory=dict)
    fill_history: List[FillEvent] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.initial_cash

    # ── Event handler ─────────────────────────────────────────

    def on_fill(self, event: FillEvent) -> None:
        """Called by engine on every FillEvent."""
        symbol = event.symbol
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        self.positions[symbol].update(event)
        self.cash -= event.net_cost
        self.fill_history.append(event)

        logger.info(
            "FILL %s %s x%.2f @ %.4f | cash=%.2f",
            event.side.value, symbol, event.quantity,
            event.fill_price, self.cash,
        )

    # ── Metrics ───────────────────────────────────────────────

    def total_equity(self, prices: Dict[str, float]) -> float:
        mv = sum(
            pos.market_value(prices.get(sym, pos.avg_price))
            for sym, pos in self.positions.items()
        )
        return self.cash + mv

    def total_realised_pnl(self) -> float:
        return sum(p.realised_pnl for p in self.positions.values())

    def summary(self, prices: Dict[str, float]) -> dict:
        equity = self.total_equity(prices)
        return {
            "cash":          round(self.cash, 2),
            "equity":        round(equity, 2),
            "pnl_realised":  round(self.total_realised_pnl(), 2),
            "pnl_unrealised": round(equity - self.initial_cash - self.total_realised_pnl(), 2),
            "positions":     {
                s: {"qty": p.quantity, "avg": p.avg_price}
                for s, p in self.positions.items() if p.quantity != 0
            },
        }
