"""Provider adapter interfaces and the HTTP contract they would sit behind.

The demo adapter returns the local catalog. It is not a licensed market-data feed.
Keys for a future provider stay in server configuration and are not read here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from market_monitor.catalog import AS_OF_ISO, primary_events
from market_monitor.model import Event


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    status: str
    as_of: str
    delay: str
    detail: str


@dataclass(frozen=True)
class SeriesResult:
    series_id: str
    as_of: str
    source: str
    delay: str
    points: tuple[tuple[str, float], ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    purpose: str


ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("GET", "/api/monitor/events", "Filter events by panel, category, geography, sector, asset, severity, source, and time."),
    Endpoint("GET", "/api/monitor/events/{id}", "One event with sources, scenarios, and timeline."),
    Endpoint("POST", "/api/monitor/events/{id}/actions", "acknowledge, assign, snooze, resolve, or dismiss when severity allows."),
    Endpoint("GET", "/api/monitor/calendar", "Scheduled items from every category."),
    Endpoint("GET", "/api/monitor/decisions", "Decision log, including audit history."),
    Endpoint("POST", "/api/monitor/decisions", "Create a decision linked to event ids. Does not place an order."),
    Endpoint("PATCH", "/api/monitor/decisions/{id}", "Update fields and append an audit record."),
    Endpoint("GET", "/api/monitor/portfolio/exposure", "Map events to a named book. Unknown overlap is null, not zero."),
    Endpoint("GET", "/api/monitor/sources", "Provider health, as-of, delay, and last error."),
    Endpoint("GET", "/api/monitor/watchlists", "Saved symbols and the events that mention them."),
)


class EventAdapter(Protocol):
    name: str

    def health(self) -> ProviderHealth: ...

    def fetch_events(self, category_id: int | None = None) -> list[Event]: ...


class SeriesAdapter(Protocol):
    name: str

    def health(self) -> ProviderHealth: ...

    def fetch_series(self, series_id: str, start: str, end: str) -> SeriesResult: ...


@dataclass
class DemoEventAdapter:
    """In-process catalog. Status is simulated, including one degraded source."""

    name: str = "Demo event catalog"
    degraded: bool = False

    def health(self) -> ProviderHealth:
        if self.degraded:
            return ProviderHealth(
                self.name, "degraded", AS_OF_ISO, "Simulated batch, not live",
                "Private-market documents in this demo are monthly and currently stale.",
            )
        return ProviderHealth(
            self.name, "simulated", AS_OF_ISO, "Simulated batch, not live",
            "Local catalog. No external call was made.",
        )

    def fetch_events(self, category_id: int | None = None) -> list[Event]:
        rows = primary_events()
        if category_id is None:
            return rows
        return [event for event in rows if event.category_id == category_id]


@dataclass
class DemoSeriesAdapter:
    name: str = "Demo series"
    failures: set[str] = field(default_factory=set)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            self.name, "simulated", AS_OF_ISO, "End-of-batch demo, not real time",
            "Chart series are generated locally.",
        )

    def fetch_series(self, series_id: str, start: str, end: str) -> SeriesResult:
        if series_id in self.failures:
            return SeriesResult(series_id, AS_OF_ISO, self.name, "n/a", error="Simulated provider timeout.")
        return SeriesResult(
            series_id, AS_OF_ISO, self.name, "Simulated batch, not live",
            points=(("2026-09-16", 1.0), ("2026-10-16", 1.02)),
        )


def source_board() -> list[ProviderHealth]:
    healthy = DemoEventAdapter()
    stale = DemoEventAdapter(name="Demo private-markets file", degraded=True)
    series = DemoSeriesAdapter()
    failed = DemoSeriesAdapter(name="Unconfigured licensed feed", failures={"quotes"})
    broken = failed.fetch_series("quotes", "2026-09-01", "2026-10-16")
    return [
        healthy.health(),
        series.health(),
        stale.health(),
        ProviderHealth(
            failed.name,
            "not configured",
            "—",
            "No entitlement",
            broken.error or "Add a server-side key before this source can be called.",
        ),
    ]
