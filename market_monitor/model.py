"""Typed records for the Market Monitor.

Values are simulated until a provider adapter is configured. An empty exposure
means the overlap with holdings is unknown. It is not zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SEVERITIES = ("critical", "high", "medium", "low", "info")
VERIFICATIONS = ("verified", "developing", "unconfirmed")
EVENT_STATUSES = ("new", "reviewing", "acknowledged", "resolved")
DECISION_STATES = ("proposed", "executed", "rejected", "deferred")
STATEMENT_KINDS = ("observed_fact", "consensus", "scenario", "interpretation")


@dataclass(frozen=True)
class Panel:
    id: str
    title: str
    summary: str


@dataclass(frozen=True)
class Category:
    id: int
    panel_id: str
    name: str
    summary: str
    cadence: str
    impacts: str
    fields: tuple[str, ...]
    event_types: tuple[str, ...]


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    retrieved_at: str


@dataclass(frozen=True)
class Scenario:
    label: str
    rationale: str


@dataclass(frozen=True)
class TimelineEntry:
    at: str
    label: str
    kind: str


@dataclass(frozen=True)
class Event:
    id: str
    category_id: int
    primary_panel: str
    event_type: str
    title: str
    summary: str
    observed_at: str
    published_at: str | None
    scheduled_at: str | None
    timezone: str
    geography: tuple[str, ...]
    sectors: tuple[str, ...]
    asset_classes: tuple[str, ...]
    instruments: tuple[str, ...]
    sources: tuple[Source, ...]
    verification: str
    severity: str
    actual: float | None
    consensus: float | None
    previous: float | None
    revised_prior: float | None
    unit: str | None
    surprise: float | None
    historical_percentile: int | None
    portfolio_exposure_pct: float | None
    impact_score: int
    interpretation: str
    scenarios: tuple[Scenario, ...]
    status: str
    related_event_ids: tuple[str, ...]
    period: str
    cadence: str
    impact_note: str
    timeline: tuple[TimelineEntry, ...]
    market_reaction: str
    dedupe_key: str
    simulated: bool = True
    delay_label: str = "Simulated batch. Not a live quote."
    impact: int = 3
    probability: int = 3
    exposure_input: int | None = None
    urgency: int = 3
    reliability: int = 4

    @property
    def observed_fact(self) -> str:
        return self.summary

    @property
    def consensus_text(self) -> str:
        if self.consensus is None:
            return "No numeric consensus is attached to this simulated item."
        unit = f" {self.unit}" if self.unit else ""
        return f"Consensus expectation {self.consensus:.2f}{unit} for {self.period}."


@dataclass(frozen=True)
class Holding:
    symbol: str
    name: str
    sector: str
    country: str
    asset_class: str
    weight_pct: float
    market_value: float
    source: str


@dataclass
class AuditRecord:
    at: str
    author: str
    action: str
    note: str
    snapshot: dict


@dataclass
class Decision:
    id: str
    title: str
    state: str
    thesis: str
    evidence: str
    positions: list[str] = field(default_factory=list)
    sizing: str = ""
    risk_budget: str = ""
    author: str = ""
    approver: str = ""
    created_at: str = ""
    follow_up: str = ""
    result: str = ""
    event_ids: list[str] = field(default_factory=list)
    history: list[AuditRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state,
            "thesis": self.thesis,
            "evidence": self.evidence,
            "positions": list(self.positions),
            "sizing": self.sizing,
            "risk_budget": self.risk_budget,
            "author": self.author,
            "approver": self.approver,
            "created_at": self.created_at,
            "follow_up": self.follow_up,
            "result": self.result,
            "event_ids": list(self.event_ids),
            "history": [
                {
                    "at": row.at,
                    "author": row.author,
                    "action": row.action,
                    "note": row.note,
                    "snapshot": row.snapshot,
                }
                for row in self.history
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Decision":
        history = [
            AuditRecord(
                at=row.get("at", ""),
                author=row.get("author", ""),
                action=row.get("action", ""),
                note=row.get("note", ""),
                snapshot=dict(row.get("snapshot") or {}),
            )
            for row in payload.get("history") or []
        ]
        return cls(
            id=payload["id"],
            title=payload.get("title", ""),
            state=payload.get("state", "proposed"),
            thesis=payload.get("thesis", ""),
            evidence=payload.get("evidence", ""),
            positions=list(payload.get("positions") or []),
            sizing=payload.get("sizing", ""),
            risk_budget=payload.get("risk_budget", ""),
            author=payload.get("author", ""),
            approver=payload.get("approver", ""),
            created_at=payload.get("created_at", ""),
            follow_up=payload.get("follow_up", ""),
            result=payload.get("result", ""),
            event_ids=list(payload.get("event_ids") or []),
            history=history,
        )
