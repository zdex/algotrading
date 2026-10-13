"""Backend service for portfolio views.

Provides a unified API for showing either:
- the live IBKR portfolio, or
- the paper-trading portfolio from local JSON state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPER_FILE = ROOT / "data" / "ibkr" / "paper_portfolio.json"
DEFAULT_LIVE_FILE = ROOT / "data" / "ibkr" / "live_snapshot.json"
LIVE_SNAPSHOTS_DIR = ROOT / "data" / "ibkr" / "live_snapshots"


@dataclass
class PortfolioSnapshot:
    mode: str
    summary: dict[str, Any] = field(default_factory=dict)
    positions: list[dict[str, Any]] = field(default_factory=list)
    connected: bool = False
    message: str | None = None


class PortfolioBackend:
    """Read and write portfolio state for the UI."""

    def __init__(self, paper_file: str | Path | None = None, ttl_seconds: int = 300, retention_count: int = 20):
        self.paper_file = Path(paper_file) if paper_file else DEFAULT_PAPER_FILE
        self.paper_file.parent.mkdir(parents=True, exist_ok=True)
        self.live_file = DEFAULT_LIVE_FILE
        self.live_file.parent.mkdir(parents=True, exist_ok=True)
        LIVE_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        # TTL (seconds) for considering a persisted live snapshot fresh
        self.ttl_seconds = int(ttl_seconds)
        # how many historical snapshot files to retain
        self.retention_count = int(retention_count)

    def _default_paper_snapshot(self) -> PortfolioSnapshot:
        positions = [
            {"symbol": "AAPL", "qty": 18, "avg_cost": 221.34, "market_price": 228.10, "market_value": 4104.0, "pnl": 122.0, "unrealized_pnl": 122.0},
            {"symbol": "MSFT", "qty": 10, "avg_cost": 412.80, "market_price": 418.55, "market_value": 4185.5, "pnl": 57.5, "unrealized_pnl": 57.5},
            {"symbol": "NVDA", "qty": 12, "avg_cost": 136.40, "market_price": 142.90, "market_value": 1714.8, "pnl": 78.0, "unrealized_pnl": 78.0},
        ]
        summary = {
            "Net liquidation": "$1,243,000",
            "Buying power": "$468,000",
            "Open positions": 3,
            "Today P&L": "+$258.50",
            "account": "Paper",
        }
        return PortfolioSnapshot(mode="paper", summary=summary, positions=positions, connected=True)

    def get_paper_snapshot(self) -> PortfolioSnapshot:
        if not self.paper_file.exists():
            return self._default_paper_snapshot()

        try:
            with open(self.paper_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return self._default_paper_snapshot()

        if not isinstance(payload, dict):
            return self._default_paper_snapshot()

        positions = payload.get("positions", [])
        summary = payload.get("summary", self._default_paper_snapshot().summary)
        if not isinstance(positions, list) or not positions:
            return self._default_paper_snapshot()

        return PortfolioSnapshot(mode="paper", summary=summary, positions=positions, connected=True)

    def save_paper_snapshot(self, positions: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> PortfolioSnapshot:
        payload = {
            "summary": summary or {
                "Net liquidation": "$0.00",
                "Buying power": "$0.00",
                "Open positions": len(positions),
                "Today P&L": "$0.00",
                "account": "Paper",
            },
            "positions": positions,
        }
        with open(self.paper_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return PortfolioSnapshot(mode="paper", summary=payload["summary"], positions=positions, connected=True)

    def get_live_snapshot(self, trader) -> PortfolioSnapshot:
        if trader is None or not getattr(trader, "connected", False):
            return PortfolioSnapshot(
                mode="live",
                summary={},
                positions=[],
                connected=False,
                message="No live IBKR account is connected right now.",
            )

        positions = trader.get_positions()
        summary = trader.get_account_summary()
        snapshot = PortfolioSnapshot(mode="live", summary=summary, positions=positions, connected=True)
        # persist a copy for UI resiliency
        try:
            self._persist_live_snapshot(summary, positions)
        except Exception:
            # non-fatal: persistence is advisory
            pass
        return snapshot
        return PortfolioSnapshot(mode="live", summary=summary, positions=positions, connected=True)

    def get_snapshot(self, actual: bool, trader=None) -> PortfolioSnapshot:
        if actual:
            return self.get_live_snapshot(trader)
        return self.get_paper_snapshot()

    def get_persisted_live_snapshot(self) -> PortfolioSnapshot:
        """Load last persisted live snapshot from disk if available."""
        import time

        if not self.live_file.exists():
            return PortfolioSnapshot(mode="live", summary={}, positions=[], connected=False,
                                     message="No persisted live snapshot available.")
        try:
            with open(self.live_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return PortfolioSnapshot(mode="live", summary={}, positions=[], connected=False,
                                     message="Failed to read persisted live snapshot.")

        ts = payload.get("ts")
        if ts is None:
            # fallback to file mtime
            age = int(time.time() - self.live_file.stat().st_mtime)
            if age > self.ttl_seconds:
                return PortfolioSnapshot(mode="live", summary=payload.get("summary", {}), positions=payload.get("positions", []), connected=False,
                                         message="Persisted live snapshot is stale.")
            return PortfolioSnapshot(mode="live", summary=payload.get("summary", {}), positions=payload.get("positions", []), connected=True)

        try:
            from datetime import datetime

            ts_dt = datetime.fromisoformat(ts)
            age = int((datetime.now() - ts_dt).total_seconds())
        except Exception:
            age = int(time.time() - self.live_file.stat().st_mtime)

        if age > self.ttl_seconds:
            return PortfolioSnapshot(mode="live", summary=payload.get("summary", {}), positions=payload.get("positions", []), connected=False,
                                     message=f"Persisted live snapshot is stale ({age}s old).")
        return PortfolioSnapshot(mode="live", summary=payload.get("summary", {}), positions=payload.get("positions", []), connected=True)

    def get_persisted_meta(self) -> dict[str, Any]:
        """Return metadata about the last persisted live snapshot (ts, age_seconds)."""
        import time

        if not self.live_file.exists():
            return {"exists": False, "ts": None, "age_seconds": None}
        try:
            with open(self.live_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return {"exists": False, "ts": None, "age_seconds": None}
        ts = payload.get("ts")
        if ts:
            try:
                from datetime import datetime

                age = int((datetime.now() - datetime.fromisoformat(ts)).total_seconds())
            except Exception:
                age = int(time.time() - self.live_file.stat().st_mtime)
            return {"exists": True, "ts": ts, "age_seconds": age}
        return {"exists": True, "ts": None, "age_seconds": int(time.time() - self.live_file.stat().st_mtime)}

    def _persist_live_snapshot(self, summary: dict[str, Any], positions: list[dict[str, Any]]) -> None:
        """Write the live snapshot to `self.live_file` and archive a timestamped copy.

        Also prune old snapshot files according to `self.retention_count`.
        """
        from datetime import datetime
        import json
        import glob

        payload = {"ts": datetime.now().isoformat(), "summary": summary, "positions": positions}
        with open(self.live_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str, indent=2)

        # archive a time-stamped copy
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived = LIVE_SNAPSHOTS_DIR / f"live_snapshot_{stamp}.json"
        with open(archived, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str, indent=2)

        # pruning: keep newest N files only
        files = sorted(glob.glob(str(LIVE_SNAPSHOTS_DIR / "live_snapshot_*.json")), reverse=True)
        for old in files[self.retention_count:]:
            try:
                Path(old).unlink()
            except Exception:
                pass

    @staticmethod
    def normalise_positions(rows: list[dict[str, Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=["symbol", "qty", "avg_cost", "market_price", "market_value", "pnl", "unrealized_pnl"])
        df = pd.DataFrame(rows)
        if "market_value" not in df.columns and {"qty", "market_price"}.issubset(df.columns):
            df["market_value"] = df["qty"].astype(float) * df["market_price"].astype(float)
        if "pnl" not in df.columns and "unrealized_pnl" in df.columns:
            df["pnl"] = df["unrealized_pnl"].astype(float)
        if "unrealized_pnl" not in df.columns and "pnl" in df.columns:
            df["unrealized_pnl"] = df["pnl"].astype(float)
        return df
