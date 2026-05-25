"""
core/events.py
--------------
All events that flow through the trading engine.
Every component communicates exclusively via these typed events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class EventType(Enum):
    BAR       = "BAR"       # OHLCV bar closed
    TICK      = "TICK"      # Live price update
    SIGNAL    = "SIGNAL"    # Strategy decision
    ORDER     = "ORDER"     # Order instruction
    FILL      = "FILL"      # Broker execution confirmation
    HALT      = "HALT"      # Risk-triggered halt


class OrderSide(Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    STOP   = "STOP"


class SignalDirection(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"   # Exit / no position


# ──────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────

@dataclass
class Event:
    type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# Market Data Events
# ──────────────────────────────────────────────

@dataclass
class BarEvent(Event):
    """One OHLCV bar (any timeframe)."""
    type:     EventType = EventType.BAR
    symbol:   str   = ""
    open:     float = 0.0
    high:     float = 0.0
    low:      float = 0.0
    close:    float = 0.0
    volume:   float = 0.0
    interval: str   = "1d"   # e.g. "1m", "5m", "1h", "1d"


@dataclass
class TickEvent(Event):
    """Real-time price tick."""
    type:   EventType = EventType.TICK
    symbol: str   = ""
    price:  float = 0.0
    size:   float = 0.0


# ──────────────────────────────────────────────
# Strategy → Risk
# ──────────────────────────────────────────────

@dataclass
class SignalEvent(Event):
    """Strategy output: directional intent, not yet sized."""
    type:      EventType       = EventType.SIGNAL
    symbol:    str             = ""
    direction: SignalDirection = SignalDirection.FLAT
    strength:  float           = 1.0   # 0–1 conviction scalar
    strategy:  str             = ""


# ──────────────────────────────────────────────
# Risk → Execution
# ──────────────────────────────────────────────

@dataclass
class OrderEvent(Event):
    """Sized, risk-approved order ready for the broker."""
    type:        EventType = EventType.ORDER
    symbol:      str       = ""
    side:        OrderSide = OrderSide.BUY
    order_type:  OrderType = OrderType.MARKET
    quantity:    float     = 0.0
    limit_price: Optional[float] = None
    stop_price:  Optional[float] = None
    order_id:    str       = ""


# ──────────────────────────────────────────────
# Broker → Portfolio
# ──────────────────────────────────────────────

@dataclass
class FillEvent(Event):
    """Confirmed execution from the broker."""
    type:       EventType = EventType.FILL
    symbol:     str       = ""
    side:       OrderSide = OrderSide.BUY
    quantity:   float     = 0.0
    fill_price: float     = 0.0
    commission: float     = 0.0
    order_id:   str       = ""

    @property
    def net_cost(self) -> float:
        sign = 1 if self.side == OrderSide.BUY else -1
        return sign * self.quantity * self.fill_price + self.commission
