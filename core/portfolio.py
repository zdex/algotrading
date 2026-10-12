"""
core/portfolio.py
-----------------
Tracks positions, cash, and P&L in real time.
Updated exclusively by FillEvents from the broker.

Every time a fill reduces or closes a position, a closed-trade record is
added to `Portfolio.trades`. That ledger is the source of truth for
per-trade P&L, win rate and the UI's trade log (pairing consecutive fills
does not work once many symbols trade at the same time).
"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

from core.events import FillEvent, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """One closed (or partially closed) round trip in a single symbol."""
    symbol:      str
    direction:   str            # "LONG" or "SHORT"
    entry_time:  Optional[datetime]
    exit_time:   datetime
    quantity:    float          # quantity closed (always positive)
    entry_price: float          # average entry price of the closed quantity
    exit_price:  float
    gross_pnl:   float
    commission:  float          # entry share + exit share of commissions
    net_pnl:     float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol:     str
    quantity:   float = 0.0       # positive = long, negative = short
    avg_price:  float = 0.0
    realised_pnl: float = 0.0
    opened_at:  Optional[datetime] = None
    entry_commission: float = 0.0  # commissions paid on the still-open quantity

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def unrealised_pnl(self, current_price: float) -> float:
        return self.quantity * (current_price - self.avg_price)

    def update(self, fill: FillEvent) -> Optional[Trade]:
        """
        Update position after a fill.

        Returns a Trade when the fill reduced, closed or reversed the
        position, otherwise None.
        """
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        if signed_qty == 0:
            return None

        # ── Opening or adding ─────────────────────────────────
        if self.quantity == 0 or (self.quantity > 0) == (signed_qty > 0):
            if self.quantity == 0:
                self.avg_price = fill.fill_price
                self.opened_at = fill.timestamp
            else:
                total_cost = self.avg_price * self.quantity + fill.fill_price * signed_qty
                self.avg_price = total_cost / (self.quantity + signed_qty)
            self.quantity += signed_qty
            self.entry_commission += fill.commission
            return None

        # ── Reducing, closing or reversing ────────────────────
        closed_qty = min(abs(self.quantity), abs(signed_qty))
        direction  = "LONG" if self.quantity > 0 else "SHORT"
        gross = closed_qty * (fill.fill_price - self.avg_price)
        if self.quantity < 0:
            gross = -gross
        self.realised_pnl += gross

        # Allocate commissions to the closed quantity
        entry_share = self.entry_commission * closed_qty / abs(self.quantity)
        exit_share  = fill.commission * closed_qty / abs(signed_qty)
        self.entry_commission -= entry_share

        trade = Trade(
            symbol      = self.symbol,
            direction   = direction,
            entry_time  = self.opened_at,
            exit_time   = fill.timestamp,
            quantity    = closed_qty,
            entry_price = self.avg_price,
            exit_price  = fill.fill_price,
            gross_pnl   = gross,
            commission  = entry_share + exit_share,
            net_pnl     = gross - entry_share - exit_share,
        )

        old_qty = self.quantity
        self.quantity += signed_qty
        if abs(self.quantity) < 1e-9:
            self.quantity = 0.0
            self.avg_price = 0.0
            self.opened_at = None
            self.entry_commission = 0.0
        elif (old_qty > 0) != (self.quantity > 0):
            # Reversed through zero: the remainder is a fresh position at the fill price
            self.avg_price = fill.fill_price
            self.opened_at = fill.timestamp
            self.entry_commission = fill.commission - exit_share
        return trade


@dataclass
class Portfolio:
    initial_cash: float = 100_000.0
    cash: float = field(init=False)
    positions: Dict[str, Position] = field(default_factory=dict)
    fill_history: List[FillEvent] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.initial_cash

    # ── Event handler ─────────────────────────────────────────

    def on_fill(self, event: FillEvent) -> None:
        """Called by engine on every FillEvent."""
        symbol = event.symbol
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        trade = self.positions[symbol].update(event)
        if trade is not None:
            self.trades.append(trade)
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

    def pnl_per_trade(self, net: bool = True) -> List[float]:
        """Per-trade P&L from the closed-trade ledger (net of commissions by default)."""
        return [t.net_pnl if net else t.gross_pnl for t in self.trades]

    def open_positions(self) -> Dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.quantity != 0}

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
