"""Local workflow store: alerts, watchlists, decisions, saved views.

Decision history is append-only. Critical and high alerts can be acknowledged,
assigned, snoozed, or resolved. They cannot be dismissed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from market_monitor.model import Decision
from market_monitor.scoring import DEFAULT_THRESHOLDS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "market_monitor" / "workflow.json"

DISMISS_BLOCKED = {"critical", "high"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict:
    return {
        "events": {},
        "decisions": [],
        "watchlist": [],
        "rules": [
            {
                "id": "rule-surprise",
                "name": "Large macro surprise",
                "category_id": 1,
                "geography": "",
                "ticker": "",
                "min_severity": "high",
                "min_surprise": 0.2,
                "min_exposure": None,
                "max_days_to_catalyst": None,
                "enabled": True,
            }
        ],
        "views": [],
        "manual_holdings": [],
        "preferences": {
            "timezone": "America/New_York",
            "density": "comfortable",
            "book": "demo",
            "thresholds": dict(DEFAULT_THRESHOLDS),
        },
    }


class WorkflowStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.data = _empty()
        self.load_error: str | None = None

    def load(self) -> "WorkflowStore":
        if not self.path.exists():
            self.data = _empty()
            self.load_error = None
            return self
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.data = _empty()
            self.load_error = f"Could not read the workflow file: {exc}"
            return self
        if not isinstance(payload, dict):
            self.data = _empty()
            self.load_error = "Workflow file was not an object. A blank store is in memory until you save."
            return self
        base = _empty()
        base.update({key: payload.get(key, base[key]) for key in base})
        self.data = base
        self.load_error = None
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        self.load_error = None

    def reset(self) -> None:
        self.data = _empty()
        self.save()

    def event_overlay(self, event_id: str) -> dict:
        return dict(self.data["events"].get(event_id) or {})

    def effective_status(self, event_id: str, catalog_status: str, now: datetime | None = None) -> str:
        overlay = self.event_overlay(event_id)
        snooze = overlay.get("snooze_until")
        if snooze:
            current = now or datetime.now(timezone.utc)
            try:
                until = datetime.fromisoformat(snooze)
            except ValueError:
                until = None
            if until is not None:
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if until > current:
                    return "snoozed"
        return overlay.get("status") or catalog_status

    def _touch(self, event_id: str, **fields) -> None:
        current = dict(self.data["events"].get(event_id) or {})
        current.update(fields)
        current["updated_at"] = _now()
        self.data["events"][event_id] = current

    def acknowledge(self, event_id: str, author: str) -> None:
        self._touch(event_id, status="acknowledged", assignee=author)

    def assign(self, event_id: str, assignee: str) -> None:
        self._touch(event_id, status="reviewing", assignee=assignee)

    def snooze(self, event_id: str, until: str) -> None:
        self._touch(event_id, snooze_until=until)

    def resolve(self, event_id: str, note: str) -> None:
        self._touch(event_id, status="resolved", resolution=note)

    def dismiss(self, event_id: str, severity: str) -> None:
        if severity in DISMISS_BLOCKED:
            raise ValueError(
                f"A {severity} alert cannot be dismissed. Acknowledge, assign, snooze, or resolve it."
            )
        self._touch(event_id, status="dismissed")

    def add_watch(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        if symbol and symbol not in self.data["watchlist"]:
            self.data["watchlist"].append(symbol)

    def remove_watch(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        self.data["watchlist"] = [item for item in self.data["watchlist"] if item != symbol]

    def add_rule(self, rule: dict) -> dict:
        rule = dict(rule)
        rule.setdefault("id", f"rule-{uuid.uuid4().hex[:8]}")
        rule.setdefault("enabled", True)
        self.data["rules"].append(rule)
        return rule

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        for rule in self.data["rules"]:
            if rule["id"] == rule_id:
                rule["enabled"] = enabled

    def save_view(self, name: str, filters: dict) -> None:
        self.data["views"] = [view for view in self.data["views"] if view.get("name") != name]
        self.data["views"].append({"name": name, "filters": filters})

    def set_manual_holdings(self, rows: list[dict]) -> None:
        self.data["manual_holdings"] = rows

    def preferences(self) -> dict:
        prefs = dict(_empty()["preferences"])
        prefs.update(self.data.get("preferences") or {})
        thresholds = dict(DEFAULT_THRESHOLDS)
        thresholds.update((self.data.get("preferences") or {}).get("thresholds") or {})
        prefs["thresholds"] = thresholds
        return prefs

    def update_preferences(self, **fields) -> None:
        prefs = self.preferences()
        prefs.update(fields)
        self.data["preferences"] = prefs

    def decisions(self) -> list[Decision]:
        return [Decision.from_dict(row) for row in self.data["decisions"]]

    def decision_by_id(self, decision_id: str) -> Decision | None:
        for row in self.decisions():
            if row.id == decision_id:
                return row
        return None

    def create_decision(self, decision: Decision) -> Decision:
        if not decision.id:
            decision.id = f"DEC-{uuid.uuid4().hex[:8]}"
        if not decision.created_at:
            decision.created_at = _now()
        decision.history.append(self._audit(decision, "created", "Decision opened."))
        self.data["decisions"].append(decision.to_dict())
        return decision

    def revise_decision(self, decision_id: str, changes: dict, author: str, note: str) -> Decision:
        if "history" in changes:
            raise ValueError("History is append-only.")
        rows = self.data["decisions"]
        for index, payload in enumerate(rows):
            if payload["id"] != decision_id:
                continue
            current = Decision.from_dict(payload)
            current.history.append(self._audit(current, "revised", note or "Fields updated.", author))
            for key, value in changes.items():
                if not hasattr(current, key) or key in {"id", "history", "created_at"}:
                    continue
                setattr(current, key, value)
            rows[index] = current.to_dict()
            return current
        raise KeyError(decision_id)

    def _audit(self, decision: Decision, action: str, note: str, author: str | None = None):
        from market_monitor.model import AuditRecord

        snapshot = decision.to_dict()
        snapshot.pop("history", None)
        return AuditRecord(
            at=_now(),
            author=author or decision.author or "analyst",
            action=action,
            note=note,
            snapshot=snapshot,
        )
