"""Portfolio-aware agent skeleton.

This file ties the AGNO workflow to the existing trading portfolio model used in
`core/portfolio.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.portfolio import Portfolio


@dataclass
class PortfolioAgentContext:
    portfolio: Optional[Portfolio] = None
    symbols: Optional[List[str]] = None
    cash: Optional[float] = None
    equity: Optional[float] = None
    positions: Optional[List[Dict[str, Any]]] = None
    trades: Optional[List[Dict[str, Any]]] = None


class PortfolioAgent:
    """Simple structured portfolio context builder for the agent.

    Replace this with AGNO Agent objects later for real reasoning or tool calls.
    """

    def __init__(self, portfolio: Optional[Portfolio] = None):
        self.portfolio = portfolio

    def build_context(self) -> str:
        if self.portfolio is None:
            return (
                "Portfolio context: no live portfolio was provided. "
                "Use sample portfolio values for demo mode."
            )

        positions = []
        for sym, pos in self.portfolio.positions.items():
            if pos.quantity != 0:
                positions.append({
                    "symbol": sym,
                    "qty": pos.quantity,
                    "avg_price": pos.avg_price,
                })

        trades = [t.to_dict() for t in self.portfolio.trades[-10:]]
        return (
            "Portfolio context:\n"
            f"Cash: ${self.portfolio.cash:,.2f}\n"
            f"Open positions: {positions}\n"
            f"Recent trades: {trades}"
        )
