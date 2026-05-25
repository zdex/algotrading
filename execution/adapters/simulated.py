"""
execution/adapters/simulated.py
--------------------------------
Paper-trading broker.  Fills market orders instantly at the
next bar's open price (realistic) with configurable slippage
and commission.

Swap this for a real broker adapter in live trading.
"""

import logging
from dataclasses import dataclass

from core.events import OrderEvent, FillEvent, OrderType, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class SimConfig:
    commission_per_trade: float = 1.00   # flat $ per trade
    slippage_bps:         float = 5.0    # basis points added to fill price


class SimulatedBroker:
    """
    Receives OrderEvents, emits FillEvents immediately.

    In a real broker adapter, on_order() would send the order
    to the exchange and wait for an async confirmation callback.
    """

    def __init__(self, engine, config: SimConfig = None):
        self.engine  = engine
        self.cfg     = config or SimConfig()
        self._prices: dict[str, float] = {}   # latest prices, updated each bar

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def on_order(self, event: OrderEvent) -> None:
        """Called by engine on every OrderEvent."""
        price = self._prices.get(event.symbol)
        if price is None:
            logger.error("No price for %s — order %s dropped.", event.symbol, event.order_id)
            return

        # Apply slippage
        slip_factor = self.cfg.slippage_bps / 10_000
        if event.side == OrderSide.BUY:
            fill_price = price * (1 + slip_factor)
        else:
            fill_price = price * (1 - slip_factor)

        fill = FillEvent(
            symbol     = event.symbol,
            side       = event.side,
            quantity   = event.quantity,
            fill_price = round(fill_price, 6),
            commission = self.cfg.commission_per_trade,
            order_id   = event.order_id,
        )

        logger.info(
            "SIM FILL %s %s x%.4f @ %.4f (slip=%.1fbps comm=%.2f)",
            event.side.value, event.symbol, event.quantity,
            fill_price, self.cfg.slippage_bps, self.cfg.commission_per_trade,
        )
        self.engine.put(fill)
