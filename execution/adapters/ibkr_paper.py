"""IBKR paper-trading adapter built on ib_insync.

This adapter connects to a local IB Gateway / TWS running in paper mode.
It exposes the small subset of functions needed by the Streamlit UI:
- connect/disconnect
- account summary
- open positions
- open orders
- submit market/limit orders

Usage:
    from execution.adapters.ibkr_paper import IBKRPaperTrader, IBKRPaperConfig
    trader = IBKRPaperTrader(IBKRPaperConfig(host="127.0.0.1", port=7497, client_id=1))
    trader.connect()
    print(trader.get_account_summary())
    trader.place_order("AAPL", "BUY", 10)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ib_insync import IB, LimitOrder, MarketOrder, Stock

logger = logging.getLogger(__name__)


@dataclass
class IBKRPaperConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1


class IBKRPaperTrader:
    """Thin wrapper around ib_insync for paper-trading workflows."""

    def __init__(self, config: IBKRPaperConfig | None = None):
        self.config = config or IBKRPaperConfig()
        self.ib = IB()
        self.connected = False
        self.connection_error: str | None = None
        self.account_id: str | None = None

    def connect(self) -> bool:
        """Connect to local IB Gateway / TWS."""
        try:
            self.ib.connect(self.config.host, self.config.port, clientId=self.config.client_id, readonly=False)
            self.connected = self.ib.isConnected()
            if self.connected:
                self.account_id = self._resolve_account_id()
                self.connection_error = None
                logger.info("Connected to IBKR paper account: %s", self.account_id)
            return self.connected
        except Exception as exc:  # pragma: no cover - runtime-only failure path
            self.connected = False
            self.connection_error = str(exc)
            logger.exception("IBKR connection failed")
            return False

    def disconnect(self) -> None:
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        self.connected = False
        self.account_id = None
        self.connection_error = None

    def _resolve_account_id(self) -> str | None:
        try:
            accounts = self.ib.managedAccounts()
            if accounts:
                return accounts[0]
        except Exception:
            pass
        try:
            for av in self.ib.accountValues():
                if av.account:
                    return av.account
        except Exception:
            pass
        return None

    def health(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "host": self.config.host,
            "port": self.config.port,
            "client_id": self.config.client_id,
            "account_id": self.account_id,
            "connection_error": self.connection_error,
        }

    def get_account_summary(self) -> dict[str, str]:
        """Fetch account values as a dictionary of tag -> value."""
        if not self.connected:
            return {}

        result: dict[str, str] = {}
        try:
            for value in self.ib.accountSummary():
                result[value.tag] = value.value
        except Exception as exc:  # pragma: no cover - depends on IB runtime
            logger.warning("Failed to load account summary: %s", exc)
        return result

    def get_positions(self) -> list[dict[str, Any]]:
        """Return current positions as rows for the UI data table."""
        if not self.connected:
            return []

        rows: list[dict[str, Any]] = []
        try:
            for pos in self.ib.positions():
                rows.append(
                    {
                        "symbol": pos.contract.symbol,
                        "exchange": pos.contract.exchange,
                        "qty": int(pos.position),
                        "avg_cost": float(pos.avgCost) if pos.avgCost is not None else 0.0,
                        "market_price": float(pos.marketPrice) if hasattr(pos, "marketPrice") and pos.marketPrice is not None else 0.0,
                        "unrealized_pnl": float(pos.unrealizedPNL) if hasattr(pos, "unrealizedPNL") and pos.unrealizedPNL is not None else 0.0,
                    }
                )
        except Exception as exc:  # pragma: no cover - depends on IB runtime
            logger.warning("Failed to load positions: %s", exc)
        return rows

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Return open orders in a UI-friendly shape."""
        if not self.connected:
            return []

        rows: list[dict[str, Any]] = []
        try:
            for order in self.ib.openOrders():
                contract = order.contract
                order_info = order.order
                rows.append(
                    {
                        "order_id": int(order_info.orderId),
                        "symbol": contract.symbol,
                        "side": order_info.side,
                        "qty": int(order_info.totalQuantity),
                        "status": getattr(order.orderStatus, "status", "UNKNOWN"),
                        "limit_price": float(order_info.lmtPrice) if order_info.lmtPrice else None,
                    }
                )
        except Exception as exc:  # pragma: no cover - depends on IB runtime
            logger.warning("Failed to load open orders: %s", exc)
        return rows

    def place_order(self, symbol: str, side: str, qty: int, limit_price: float | None = None) -> dict[str, Any]:
        """Submit an order to the connected IBKR paper account."""
        if not self.connected:
            raise RuntimeError("IBKR is not connected. Connect to IB Gateway/TWS first.")

        contract = Stock(symbol.upper(), "SMART", "USD")
        side_name = str(side).upper()
        if limit_price is not None:
            ib_order = LimitOrder(side_name, int(qty), float(limit_price))
        else:
            ib_order = MarketOrder(side_name, int(qty))

        trade = self.ib.placeOrder(contract, ib_order)
        order_id = getattr(trade, "orderId", None)
        if order_id is None and hasattr(trade, "order"):
            order_id = getattr(trade.order, "orderId", None)

        return {
            "order_id": order_id,
            "symbol": symbol.upper(),
            "side": side_name,
            "qty": int(qty),
            "limit_price": float(limit_price) if limit_price is not None else None,
            "status": "Submitted",
        }
