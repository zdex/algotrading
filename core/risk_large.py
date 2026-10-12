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

Point-in-time
-------------
Volatility and correlation are computed only from prices up to the bar
that produced the signal (the signal's timestamp). Earlier versions used
`prices_df.tail(...)`, i.e. the last days of the whole dataset, which
leaked future data into every backtest decision.

Pending orders
--------------
With a next-open fill model, orders created today fill tomorrow. The risk
manager therefore counts its own unfilled orders when it checks position
count, gross exposure and sector exposure, so a burst of signals on one
day cannot blow through the limits.

Decision log
------------
Every signal produces one record in `self.decisions` (approved, closed,
rejected with the check that failed, ignored). `rejections()` returns the
rejected subset. The UI reads both.

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
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from core.events import (
    BarEvent, SignalEvent, OrderEvent, OrderSide, OrderType, SignalDirection,
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
    drawdown_from_peak: bool  = True     # True: measure from peak equity; False: from starting cash

    # Sector limits
    max_sector_pct:     float = 0.25     # max 25% of equity in one sector

    # Correlation filter
    max_correlation:    float = 0.85     # reject if corr with existing > 0.85
    corr_lookback:      int   = 60       # days for correlation calculation

    # Volatility targeting
    use_vol_targeting:  bool  = True     # scale size by inverse volatility
    target_annual_vol:  float = 0.15     # see vol_target_mode
    vol_lookback:       int   = 20       # days for vol estimate
    # "portfolio"    : target_annual_vol is a PORTFOLIO target, split evenly across
    #                  max_open_positions slots: notional = equity × (target / slots) / vol.
    #                  With the defaults a 30%-vol stock gets 1% of equity, a 15%-vol stock 2%.
    # "per_position" : original formula, notional = equity × target / vol. With a 2% cap this
    #                  binds for any stock under 750% vol, so every position ends up at 2%.
    vol_target_mode:    str   = "portfolio"


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
        self.prices_df  = prices_df
        self.cfg        = config or LargeUniverseRiskConfig()
        self._halted    = False
        self._prices: dict[str, float] = {}    # latest bar closes
        self._peak_equity = portfolio.initial_cash

        # Orders sent but not yet filled: order_id → (symbol, signed qty)
        self._pending: dict[str, tuple[str, float]] = {}
        self._fills_seen = 0

        self.decisions: list[dict] = []

        if self.prices_df is not None and not self.prices_df.empty:
            self.prices_df = self.prices_df.sort_index()
            self._returns = self.prices_df.pct_change(fill_method=None)
        else:
            self._returns = None

    # ── Price / equity updates ────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def update_bar(self, event: BarEvent) -> None:
        self._prices[event.symbol] = event.close

    def update_equity(self, equity: float) -> None:
        """Called by the runner once per day so the drawdown peak is tracked."""
        self._peak_equity = max(self._peak_equity, equity)

    # ── Main handler ──────────────────────────────────────────

    def on_signal(self, event: SignalEvent) -> None:
        self._reconcile_fills()
        ts     = event.timestamp
        equity = self.portfolio.total_equity(self._prices)
        self._peak_equity = max(self._peak_equity, equity)
        held   = self._effective_qty(event.symbol)

        # ── Exits are always allowed, even when halted ────────
        if event.direction == SignalDirection.FLAT:
            if held == 0:
                self._record(event, "ignored", "no_position")
                return
            self._close_position(event.symbol, ts)
            self._record(event, "closed", quantity=abs(held))
            return

        if self._halted:
            logger.warning("RISK HALT — signal for %s rejected.", event.symbol)
            self._record(event, "rejected", "halted")
            return

        # ── 1. Drawdown halt ──────────────────────────────────
        base = self._peak_equity if self.cfg.drawdown_from_peak else self.portfolio.initial_cash
        dd = 1 - equity / base if base else 0.0
        if dd >= self.cfg.max_drawdown_pct:
            logger.error("HALT! Drawdown %.1f%% ≥ limit.", dd * 100)
            self._halted = True
            self._record(event, "rejected", "drawdown_halt", dd, self.cfg.max_drawdown_pct)
            return

        want_long = event.direction == SignalDirection.LONG

        # ── 2. Already positioned the same way ────────────────
        if (held > 0 and want_long) or (held < 0 and not want_long):
            self._record(event, "ignored", "already_in_position")
            return

        # ── 3. Reversal: close the opposite position first ────
        reversing = held != 0
        if reversing:
            self._close_position(event.symbol, ts)

        # ── 4. Open position count ────────────────────────────
        open_count = self._open_count(exclude=event.symbol)
        if open_count >= self.cfg.max_open_positions:
            logger.debug("Position limit %d reached.", self.cfg.max_open_positions)
            self._record(event, "rejected", "max_open_positions",
                         open_count, self.cfg.max_open_positions)
            return

        # ── 5. Sizing ─────────────────────────────────────────
        price = self._prices.get(event.symbol)
        if not price:
            logger.warning("No price for %s.", event.symbol)
            self._record(event, "rejected", "no_price")
            return
        quantity = self._size_position(event.symbol, equity, price, event.strength, ts)
        if quantity <= 0:
            self._record(event, "rejected", "zero_size")
            return
        notional = quantity * price

        # ── 6. Portfolio heat (gross exposure after this order) ─
        gross_after = (self._gross_value(exclude=event.symbol) + notional) / equity if equity else 0
        if gross_after > self.cfg.max_gross_exposure + 1e-9:
            logger.debug("Gross exposure %.1f%% would exceed cap — %s rejected.",
                         gross_after * 100, event.symbol)
            self._record(event, "rejected", "max_gross_exposure",
                         gross_after, self.cfg.max_gross_exposure)
            return

        # ── 7. Sector concentration (after this order) ────────
        sector = self._sector(event.symbol)
        if sector is not None:
            sector_after = (self._sector_value(sector, exclude=event.symbol) + notional) / equity
            if sector_after > self.cfg.max_sector_pct + 1e-9:
                logger.debug("Sector '%s' would be %.1f%% — %s rejected.",
                             sector, sector_after * 100, event.symbol)
                self._record(event, "rejected", "max_sector_pct",
                             sector_after, self.cfg.max_sector_pct, detail=sector)
                return

        # ── 8. Correlation filter ─────────────────────────────
        max_corr, against = self._max_correlation(event.symbol, ts)
        if max_corr is not None and max_corr >= self.cfg.max_correlation:
            logger.debug("%s rejected: max correlation %.2f with %s",
                         event.symbol, max_corr, against)
            self._record(event, "rejected", "max_correlation",
                         max_corr, self.cfg.max_correlation, detail=against)
            return

        side = OrderSide.BUY if want_long else OrderSide.SELL
        self._send(event.symbol, side, round(quantity, 6), ts)
        logger.info("APPROVED %s %s x%.4f @ %.2f", side.value, event.symbol, quantity, price)
        self._record(event, "reversed" if reversing else "approved",
                     quantity=quantity, price=price, value=notional / equity if equity else None)

    # ── Sizing ────────────────────────────────────────────────

    def _size_position(
        self,
        symbol:   str,
        equity:   float,
        price:    float,
        strength: float,
        ts:       Optional[datetime] = None,
    ) -> float:
        """
        Volatility-targeted position sizing (see LargeUniverseRiskConfig.vol_target_mode),
        always capped at max_position_pct of equity.
        """
        notional = self.target_notional(symbol, equity, strength, ts)
        return notional / price

    def target_notional(self, symbol: str, equity: float, strength: float = 1.0,
                        ts: Optional[datetime] = None) -> float:
        max_notional = equity * self.cfg.max_position_pct
        notional = equity * self.cfg.default_order_pct * strength

        if self.cfg.use_vol_targeting and self._returns is not None:
            vol = self._annual_vol(symbol, ts)
            if vol and vol > 0:
                target = self.cfg.target_annual_vol
                if self.cfg.vol_target_mode == "portfolio":
                    target = target / max(1, self.cfg.max_open_positions)
                notional = equity * target / vol * strength
            else:
                notional = equity * self.cfg.default_order_pct
        return min(notional, max_notional)

    def _history(self, columns: list[str], ts: Optional[datetime], rows: int) -> pd.DataFrame:
        """Return rows of daily returns up to and including `ts` (no future data)."""
        rets = self._returns
        if ts is None:
            end = len(rets)
        else:
            end = rets.index.searchsorted(pd.Timestamp(ts), side="right")
        start = max(0, end - rows)
        return rets.iloc[start:end][columns]

    def _annual_vol(self, symbol: str, ts: Optional[datetime] = None) -> float | None:
        """Estimate annualised volatility from returns before the signal."""
        if self._returns is None or symbol not in self._returns.columns:
            return None
        returns = self._history([symbol], ts, self.cfg.vol_lookback)[symbol].dropna()
        if len(returns) < 5:
            return None
        return float(returns.std() * math.sqrt(252))

    # ── Sector / correlation ──────────────────────────────────

    def _sector(self, symbol: str) -> Optional[str]:
        """Sector for the cap. Unknown names share an 'Unknown' bucket so they can't bypass it."""
        if not self.sector_map:
            return None    # no sector data at all — check disabled
        return self.sector_map.get(symbol, "Unknown")

    def _max_correlation(self, symbol: str, ts: Optional[datetime]) -> tuple[Optional[float], Optional[str]]:
        if self._returns is None or symbol not in self._returns.columns:
            return None, None
        open_symbols = [
            s for s in self._held_symbols()
            if s != symbol and s in self._returns.columns
        ]
        if not open_symbols:
            return None, None
        window = self._history(open_symbols + [symbol], ts, self.cfg.corr_lookback)
        window = window.dropna(how="all")
        if len(window) < 10:
            return None, None
        corr = window.corr()[symbol].drop(symbol).abs().dropna()
        if corr.empty:
            return None, None
        return float(corr.max()), str(corr.idxmax())

    # Kept for backward compatibility with older callers
    def _sector_check(self, symbol: str, equity: float) -> bool:
        sector = self._sector(symbol)
        if sector is None or not equity:
            return True
        return self._sector_value(sector) / equity < self.cfg.max_sector_pct

    def _correlation_check(self, symbol: str) -> bool:
        max_corr, _ = self._max_correlation(symbol, None)
        return max_corr is None or max_corr < self.cfg.max_correlation

    # ── Position bookkeeping (positions + own pending orders) ─

    def _reconcile_fills(self) -> None:
        history = self.portfolio.fill_history
        for fill in history[self._fills_seen:]:
            self._pending.pop(fill.order_id, None)
        self._fills_seen = len(history)

    def _pending_qty(self, symbol: str) -> float:
        return sum(q for s, q in self._pending.values() if s == symbol)

    def _effective_qty(self, symbol: str) -> float:
        pos = self.portfolio.positions.get(symbol)
        qty = (pos.quantity if pos else 0.0) + self._pending_qty(symbol)
        return 0.0 if abs(qty) < 1e-9 else qty

    def _held_symbols(self) -> set[str]:
        symbols = {s for s, p in self.portfolio.positions.items() if p.quantity != 0}
        symbols |= {s for s, _ in self._pending.values()}
        return {s for s in symbols if self._effective_qty(s) != 0}

    def _open_count(self, exclude: str = None) -> int:
        return sum(1 for s in self._held_symbols() if s != exclude)

    def _value(self, symbol: str) -> float:
        pos   = self.portfolio.positions.get(symbol)
        price = self._prices.get(symbol, pos.avg_price if pos else 0.0)
        return self._effective_qty(symbol) * price

    def _gross_value(self, exclude: str = None) -> float:
        return sum(abs(self._value(s)) for s in self._held_symbols() if s != exclude)

    def _sector_value(self, sector: str, exclude: str = None) -> float:
        return sum(
            abs(self._value(s)) for s in self._held_symbols()
            if s != exclude and self._sector(s) == sector
        )

    def _gross_exposure(self, equity: float) -> float:
        return self._gross_value() / equity if equity else 0

    # ── Orders ────────────────────────────────────────────────

    def _send(self, symbol: str, side: OrderSide, quantity: float, ts) -> None:
        extra = {"timestamp": ts} if ts is not None else {}
        order = OrderEvent(
            symbol     = symbol,
            side       = side,
            order_type = OrderType.MARKET,
            quantity   = quantity,
            order_id   = str(uuid.uuid4())[:8],
            **extra,
        )
        signed = quantity if side == OrderSide.BUY else -quantity
        self._pending[order.order_id] = (symbol, signed)
        self.engine.put(order)

    def _close_position(self, symbol: str, ts=None) -> None:
        qty = self._effective_qty(symbol)
        if qty == 0:
            return
        side = OrderSide.SELL if qty > 0 else OrderSide.BUY
        logger.info("CLOSE %s %s", symbol, side.value)
        self._send(symbol, side, abs(qty), ts)

    # ── Decision log ──────────────────────────────────────────

    def _record(self, event: SignalEvent, action: str, check: str = "",
                value=None, limit=None, detail: str = "", quantity=None, price=None) -> None:
        self.decisions.append({
            "timestamp": event.timestamp,
            "symbol":    event.symbol,
            "direction": event.direction.value,
            "strategy":  event.strategy,
            "action":    action,
            "check":     check,
            "value":     value,
            "limit":     limit,
            "detail":    detail,
            "quantity":  quantity,
            "price":     price,
        })

    def rejections(self) -> list[dict]:
        return [d for d in self.decisions if d["action"] == "rejected"]

    # ── Monitoring ────────────────────────────────────────────

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

        gross = sum(
            abs(p.market_value(self._prices.get(s, p.avg_price)))
            for s, p in self.portfolio.positions.items()
        )
        return {
            "equity":           round(equity, 2),
            "gross_exposure":   round(gross / equity, 4) if equity else 0.0,
            "open_positions":   sum(1 for p in self.portfolio.positions.values() if p.quantity != 0),
            "halted":           self._halted,
            "peak_equity":      round(self._peak_equity, 2),
            "sector_exposure":  {
                k: round(v / equity, 4) for k, v in sector_exposure.items()
            } if equity else {},
        }

    def reset_halt(self) -> None:
        self._halted = False
        logger.info("Risk halt cleared.")
