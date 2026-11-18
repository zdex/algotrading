"""Run the trading desk on a clock after the user starts it.

The first pass can fire immediately. Later passes follow a fixed interval, or
a daily, monthly, or quarterly clock time. APScheduler keeps the job on this
process.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agents.agno.trading_desk import DEFAULT_ORDERS, DeskCompany, TradingDesk

SCHEDULE_CHOICES = (
    ("Every 15 minutes", "interval", 15),
    ("Every 30 minutes", "interval", 30),
    ("Every hour", "interval", 60),
    ("Every 4 hours", "interval", 240),
    ("Daily", "daily", None),
    ("Monthly", "monthly", None),
    ("Quarterly", "quarterly", None),
)


@dataclass(frozen=True)
class DeskSchedule:
    every_minutes: int | None = 30
    daily_at: time | None = None
    cadence: str = "interval"

    @property
    def kind(self) -> str:
        """Interval, or a clock. A missing interval stays daily for older callers."""
        if self.cadence == "interval" and self.every_minutes is None:
            return "daily"
        return self.cadence

    def label(self) -> str:
        if self.kind == "interval":
            minutes = self.every_minutes or 0
            if minutes % 60 == 0 and minutes:
                hours = minutes // 60
                unit = "hour" if hours == 1 else "hours"
                return f"every {hours} {unit}"
            return f"every {minutes} minutes"
        if self.daily_at is None:
            raise ValueError("This schedule needs a clock time.")
        clock = self.daily_at.strftime("%H:%M")
        if self.kind == "daily":
            return f"daily at {clock}"
        if self.kind == "monthly":
            return f"monthly on day 1 at {clock}"
        if self.kind == "quarterly":
            return f"quarterly on day 1 (Jan, Apr, Jul, Oct) at {clock}"
        raise ValueError(f"Unknown schedule {self.kind}.")


def trigger_for(schedule: DeskSchedule):
    if schedule.kind == "interval":
        if not schedule.every_minutes or schedule.every_minutes < 1:
            raise ValueError("The interval has to be at least one minute.")
        return IntervalTrigger(minutes=schedule.every_minutes)
    if schedule.daily_at is None:
        raise ValueError("This schedule needs a clock time.")
    clock = {"hour": schedule.daily_at.hour, "minute": schedule.daily_at.minute}
    if schedule.kind == "daily":
        return CronTrigger(**clock)
    if schedule.kind == "monthly":
        return CronTrigger(day=1, **clock)
    if schedule.kind == "quarterly":
        return CronTrigger(month="1,4,7,10", day=1, **clock)
    raise ValueError(f"Unknown schedule {schedule.kind}.")


class ScheduledRunner:
    """One company list, one schedule, and the latest desk snapshot."""

    def __init__(
        self,
        companies: list[DeskCompany],
        schedule: DeskSchedule,
        orders_path: Path | None = None,
        desk_factory=None,
        label: str = "Agent",
    ):
        self.companies = list(companies)
        self.schedule = schedule
        self.label = label
        self.orders_path = orders_path or DEFAULT_ORDERS
        self._desk_factory = desk_factory or (lambda: TradingDesk(orders_path=self.orders_path))
        self._scheduler = BackgroundScheduler(daemon=True)
        self._job_id = "trading-desk"
        self._lock = threading.Lock()
        self.latest: dict | None = None
        self.error: str | None = None
        self.in_run = False
        self.run_count = 0
        self.last_started: datetime | None = None
        self.last_finished: datetime | None = None

    def start(self, *, immediate: bool = True) -> None:
        if self._scheduler.running:
            raise RuntimeError("The agent is already scheduled.")
        now = datetime.now().astimezone()
        if self.schedule.kind == "interval":
            first = now if immediate else now + timedelta(minutes=self.schedule.every_minutes or 0)
        else:
            first = now if immediate else None
        options = {
            "id": self._job_id,
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 120,
        }
        if first is not None:
            options["next_run_time"] = first
        self._scheduler.add_job(self.run_once, trigger_for(self.schedule), **options)
        self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    @property
    def active(self) -> bool:
        return bool(self._scheduler.running)

    def next_run_at(self) -> datetime | None:
        if not self._scheduler.running:
            return None
        job = self._scheduler.get_job(self._job_id)
        if job is None:
            return None
        return job.next_run_time

    def run_once(self) -> None:
        with self._lock:
            self.last_started = datetime.now().astimezone()
            self.error = None
            self.in_run = True
        try:
            desk = self._desk_factory()

            def publish(desk_state) -> None:
                with self._lock:
                    self.latest = desk_state.to_dict()

            result = desk.run(self.companies, on_update=publish)
            with self._lock:
                self.latest = result.to_dict()
                self.run_count += 1
                self.last_finished = datetime.now().astimezone()
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
        finally:
            with self._lock:
                self.in_run = False

    def view(self) -> dict:
        with self._lock:
            snapshot = {
                "in_run": self.in_run,
                "run_count": self.run_count,
                "error": self.error,
                "last_started": self.last_started,
                "last_finished": self.last_finished,
                "latest": self.latest,
                "schedule": self.schedule.label(),
                "symbols": [company.symbol for company in self.companies],
                "label": self.label,
            }
        snapshot["active"] = self.active
        snapshot["next_run_at"] = self.next_run_at()
        return snapshot
