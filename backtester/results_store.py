"""
backtester/results_store.py
---------------------------
Saves each backtest run to disk so the UI can list, reload and compare
runs without re-running them.

Layout
------
results/<run_id>/
    config.json        BacktestConfig
    metrics.json       performance metrics
    meta.json          timings, universe sizes, warnings
    sector_exposure.json
    equity.parquet     benchmarks.parquet   trades.parquet   fills.parquet
    decisions.parquet  positions.parquet    liquidity_rejections.parquet
    signal_summary.parquet
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Optional

import pandas as pd

from backtester.runner import BacktestConfig, BacktestResult

RESULTS_DIR = "./results"

_FRAMES = [
    "equity", "benchmarks", "trades", "fills", "decisions",
    "positions", "liquidity_rejections", "signal_summary",
]


def _json_default(o):
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def new_run_id(name: str = "") -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:40]
    return f"{stamp}-{slug}" if slug else stamp


def save_result(result: BacktestResult, results_dir: str = RESULTS_DIR,
                run_id: Optional[str] = None) -> str:
    run_id = run_id or new_run_id(result.config.name)
    path = os.path.join(results_dir, run_id)
    os.makedirs(path, exist_ok=True)

    for name, obj in [
        ("config", result.config.to_dict()),
        ("metrics", result.metrics),
        ("meta", {**result.meta, "run_id": run_id}),
        ("sector_exposure", result.sector_exposure),
    ]:
        with open(os.path.join(path, f"{name}.json"), "w") as f:
            json.dump(obj, f, indent=2, default=_json_default)

    for name in _FRAMES:
        df = getattr(result, name)
        if df is None:
            continue
        df = df.copy()
        # Mixed-type object columns (e.g. decision values) → strings for Parquet
        for col in df.columns:
            if df[col].dtype == object:
                sample = df[col].dropna()
                if not sample.empty and not all(isinstance(v, str) for v in sample.head(200)):
                    if not all(isinstance(v, (int, float)) for v in sample.head(200)):
                        df[col] = df[col].map(lambda v: v if v is None or isinstance(v, str) else str(v))
        df.to_parquet(os.path.join(path, f"{name}.parquet"))
    return run_id


def list_runs(results_dir: str = RESULTS_DIR) -> pd.DataFrame:
    """One row per saved run, newest first, with headline metrics."""
    rows = []
    if os.path.isdir(results_dir):
        for run_id in os.listdir(results_dir):
            path = os.path.join(results_dir, run_id)
            mpath = os.path.join(path, "metrics.json")
            if not os.path.isfile(mpath):
                continue
            try:
                with open(mpath) as f:
                    metrics = json.load(f)
                with open(os.path.join(path, "config.json")) as f:
                    config = json.load(f)
                with open(os.path.join(path, "meta.json")) as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            rows.append({
                "run_id":      run_id,
                "name":        config.get("name") or "",
                "created_at":  meta.get("created_at"),
                "period":      f"{config.get('start_date')} → {config.get('end_date')}",
                "symbols":     meta.get("tradeable_size"),
                "total_return_pct": metrics.get("total_return_pct"),
                "cagr_pct":    metrics.get("cagr_pct"),
                "sharpe":      metrics.get("sharpe"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "num_trades":  metrics.get("num_trades"),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("created_at", ascending=False).reset_index(drop=True)
    return df


def load_result(run_id: str, results_dir: str = RESULTS_DIR) -> BacktestResult:
    path = os.path.join(results_dir, run_id)

    def j(name):
        with open(os.path.join(path, f"{name}.json")) as f:
            return json.load(f)

    frames = {}
    for name in _FRAMES:
        fp = os.path.join(path, f"{name}.parquet")
        frames[name] = pd.read_parquet(fp) if os.path.exists(fp) else pd.DataFrame()

    return BacktestResult(
        config=BacktestConfig.from_dict(j("config")),
        metrics=j("metrics"),
        meta=j("meta"),
        sector_exposure=j("sector_exposure"),
        **frames,
    )


def delete_run(run_id: str, results_dir: str = RESULTS_DIR) -> None:
    path = os.path.join(results_dir, run_id)
    if os.path.isdir(path) and os.path.abspath(path).startswith(os.path.abspath(results_dir)):
        shutil.rmtree(path)
