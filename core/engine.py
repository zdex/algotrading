"""
core/engine.py
--------------
Central event loop.  Components register handlers; the engine
dispatches events in FIFO order until the queue is empty.

Same loop runs in backtest mode (historical feed) and live mode
(WebSocket feed) — only the DataFeed differs.
"""

import queue
import logging
from typing import Callable, Dict, List

from core.events import Event, EventType

logger = logging.getLogger(__name__)


class EventEngine:
    """
    Lightweight synchronous event bus.

    Usage
    -----
    engine = EventEngine()
    engine.register(EventType.BAR,    strategy.on_bar)
    engine.register(EventType.SIGNAL, risk.on_signal)
    engine.register(EventType.ORDER,  broker.on_order)
    engine.register(EventType.FILL,   portfolio.on_fill)
    engine.start(data_feed)
    """

    def __init__(self):
        self._queue: queue.Queue[Event] = queue.Queue()
        self._handlers: Dict[EventType, List[Callable]] = {
            et: [] for et in EventType
        }
        self._running = False

    # ── Registration ──────────────────────────────────────────

    def register(self, event_type: EventType, handler: Callable) -> None:
        """Attach a handler function to an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("Registered %s → %s", event_type.value, handler.__qualname__)

    def unregister(self, event_type: EventType, handler: Callable) -> None:
        self._handlers[event_type].remove(handler)

    # ── Queue interface ────────────────────────────────────────

    def put(self, event: Event) -> None:
        """Any component can emit events via this method."""
        self._queue.put(event)

    def _dispatch(self, event: Event) -> None:
        for handler in self._handlers.get(event.type, []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Handler %s raised on %s", handler.__qualname__, event
                )

    # ── Main loop ─────────────────────────────────────────────

    def start(self, data_feed) -> None:
        """
        Run the engine.

        Parameters
        ----------
        data_feed : iterable of BarEvent / TickEvent
            Historical feed  →  a generator over a DataFrame
            Live feed        →  a WebSocket wrapper that yields events
        """
        self._running = True
        logger.info("Engine started.")

        for market_event in data_feed:
            if not self._running:
                break

            # Seed the queue with the incoming market event
            self.put(market_event)

            # Drain everything that event (and its descendants) produced
            while not self._queue.empty():
                event = self._queue.get(block=False)
                logger.debug("Dispatching %s", event)
                self._dispatch(event)

        logger.info("Engine stopped. Queue empty: %s", self._queue.empty())
        self._running = False

    def stop(self) -> None:
        self._running = False
