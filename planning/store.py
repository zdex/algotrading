"""JSON files for investment plans. One file per plan under data/plans/."""

from __future__ import annotations

import json
from pathlib import Path

from planning.model import Plan, new_plan, slugify

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "plans"


class PlanStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else DEFAULT_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, plan_id: str) -> Path:
        return self.directory / f"{plan_id}.json"

    def list_plans(self) -> list[Plan]:
        plans: list[Plan] = []
        for path in sorted(self.directory.glob("*.json")):
            plan = self._read(path)
            if plan is not None:
                plans.append(plan)
        plans.sort(key=lambda plan: (plan.status != "active", plan.name.casefold()))
        return plans

    def load(self, plan_id: str) -> Plan | None:
        return self._read(self.path_for(plan_id))

    def create(self, name: str) -> Plan:
        base = slugify(name)
        plan_id = base
        suffix = 2
        while self.path_for(plan_id).exists():
            plan_id = f"{base}-{suffix}"
            suffix += 1
        plan = new_plan(name, plan_id)
        self.save(plan)
        return plan

    def save(self, plan: Plan, *, make_active: bool = False) -> Plan:
        from datetime import datetime

        plan.updated_at = datetime.now().replace(microsecond=0).isoformat()
        if make_active or plan.status == "active":
            plan.status = "active"
            for other in self.list_plans():
                if other.id == plan.id or other.status != "active":
                    continue
                other.status = "draft"
                self._write(other)
        self._write(plan)
        return plan

    def delete(self, plan_id: str) -> None:
        path = self.path_for(plan_id)
        if path.exists():
            path.unlink()

    def _read(self, path: Path) -> Plan | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not payload.get("id"):
            return None
        return Plan.from_dict(payload)

    def _write(self, plan: Plan) -> None:
        path = self.path_for(plan.id)
        path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
