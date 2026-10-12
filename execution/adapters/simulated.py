"""
execution/adapters/simulated.py
--------------------------------
Paper-trading broker for backtests.

Fill model (default, fill_timing="next_open")
---------------------------------------------
A market order created while processing bar t (i.e. after bar t has
closed) is held until the next bar for that symbol arrives, then filled
at that bar's OPEN plus slippage. This removes the same-bar look-ahead
of filling at the close the signal was computed from.

To use it, register the broker's bar handler BEFORE the strategy so that
yesterday's orders fill before today's signals are generated:

    engine.register(EventType.BAR,   broker.on_bar)
    engine.register(EventType.BAR,   strategy.on_bar)
    engine.register(EventType.ORDER, broker.on_order)

fill_timing="close" keeps the old behaviour (instant fill at the latest
close). If on_bar() is never called (older wiring that only calls
update_price()), the broker falls back to that behaviour and logs a
warning once, so existing scripts keep working.

Swap this for a real broker adapter in live trading.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.events import BarEvent, OrderEvent, FillEvent, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class SimConfig:
    commission_per_trade: float = 1.00   # flat $ per trade
    slippage_bps:         float = 5.0    # basis points added to fill price
    fill_timing:          str   = "next_open"   # "next_open" | "close"


class SimulatedBroker:
    """
    Receives OrderEvents and emits FillEvents.

    In a real broker adapter, on_order() would send the order
    to the exchange and wait for an async confirmation callback.
    """

    def __init__(self, engine, config: SimConfig = None):
        self.engine  = engine
        self.cfg     = config or SimConfig()
        self._prices: dict[str, float] = {}   # latest close per symbol
        self._pending: dict[str, list[OrderEvent]] = {}
        self._bar_mode = False                # True once on_bar() has been called
        self._warned_legacy = False

    # ── Market data ───────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def on_bar(self, event: BarEvent) -> None:
        """Fill any orders waiting for this symbol at the bar's open, then record the close."""
        self._bar_mode = True
        waiting = self._pending.pop(event.symbol, None)
        if waiting:
            for order in waiting:
                self._fill(order, event.open, event.timestamp)
        self._prices[event.symbol] = event.close

    # ── Orders ────────────────────────────────────────────────

    def on_order(self, event: OrderEvent) -> None:
        """Called by engine on every OrderEvent."""
        if self.cfg.fill_timing == "next_open":
            if self._bar_mode:
                self._pending.setdefault(event.symbol, []).append(event)
                return
            if not self._warned_legacy:
                logger.warning(
                    "SimulatedBroker.on_bar() is not registered — filling at the latest "
                    "close (same-bar look-ahead). Register broker.on_bar before the strategy."
                )
                self._warned_legacy = True

        price = self._prices.get(event.symbol)
        if price is None:
            logger.error("No price for %s — order %s dropped.", event.symbol, event.order_id)
            return
        self._fill(event, price, event.timestamp)

    def pending_orders(self) -> list[OrderEvent]:
        """Orders still waiting for a next bar (e.g. created on the final bar)."""
        return [o for orders in self._pending.values() for o in orders]

    # ── Internals ─────────────────────────────────────────────

    def _fill(self, order: OrderEvent, price: float, ts: Optional[datetime]) -> None:
        slip_factor = self.cfg.slippage_bps / 10_000
        if order.side == OrderSide.BUY:
            fill_price = price * (1 + slip_factor)
        else:
            fill_price = price * (1 - slip_factor)

        extra = {"timestamp": ts} if ts is not None else {}
        fill = FillEvent(
            symbol     = order.symbol,
            side       = order.side,
            quantity   = order.quantity,
            fill_price = round(fill_price, 6),
            commission = self.cfg.commission_per_trade,
            order_id   = order.order_id,
            **extra,
        )

        logger.info(
            "SIM FILL %s %s x%.4f @ %.4f (slip=%.1fbps comm=%.2f)",
            order.side.value, order.symbol, order.quantity,
            fill_price, self.cfg.slippage_bps, self.cfg.commission_per_trade,
        )
        self.engine.put(fill)
