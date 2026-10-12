"""
backtester/runner.py
--------------------
The large-universe backtest pipeline as a reusable function.

    from backtester.runner import BacktestConfig, run_backtest
    result = run_backtest(BacktestConfig(start_date="2021-01-01"))
    result.metrics["sharpe"], result.equity, result.trades

Used by run_backtest_large.py (CLI) and the Streamlit UI. Unlike the old
script, it RETURNS everything instead of printing it:

- a DAILY, date-indexed equity curve (one point per trading day)
- the closed-trade ledger from Portfolio.trades
- every fill, and every risk decision (approved / rejected + reason)
- final positions, sector exposure, liquidity-filter rejections
- performance metrics (date-aware, plus alpha/beta vs the first benchmark)

Pipeline
--------
1. Universe       (cached dated snapshot of index constituents)
2. Data           (download with warm-up history; cache checks coverage)
3. Liquidity      (filter as of the START date — no look-ahead)
4. Signals        (vectorised, computed on warm-up + test period)
5. Engine         (next-open fills, point-in-time risk checks)
6. Results
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from core.engine     import EventEngine
from core.events     import EventType, BarEvent
from core.portfolio  import Portfolio
from core.risk_large import LargeUniverseRiskManager, LargeUniverseRiskConfig
from data.feed       import DataFeed
from data.filters    import LiquidityFilter, FilterConfig
from data.universe   import load_universe, select_symbols, UNIVERSE_FILE
from execution.adapters.simulated import SimulatedBroker, SimConfig
from strategy.examples.ma_crossover_vectorised import (
    VectorisedMACrossover, MACrossoverConfig, PrecomputedSignalStrategy,
)
from backtester.metrics import performance_report, drawdown_series

logger = logging.getLogger("backtest_large")

STEPS = [
    "Universe",
    "Download data",
    "Liquidity filter",
    "Generate signals",
    "Run engine",
    "Results",
]

SURVIVORSHIP_WARNING = (
    "Universe = today's index constituents. Stocks that left the indexes during "
    "the backtest are missing (survivorship bias), so results are likely optimistic."
)


# ── Config ────────────────────────────────────────────────────

def _default_filter() -> FilterConfig:
    return FilterConfig(min_adv_usd=5_000_000, min_price=5.0, min_history_days=400)


def _default_risk() -> LargeUniverseRiskConfig:
    return LargeUniverseRiskConfig(
        max_position_pct   = 0.02,
        default_order_pct  = 0.01,
        max_open_positions = 50,
        max_sector_pct     = 0.25,
        max_correlation    = 0.85,
        use_vol_targeting  = True,
        target_annual_vol  = 0.15,
    )


@dataclass
class BacktestConfig:
    name:           str   = ""
    start_date:     str   = "2021-01-01"
    end_date:       str   = "2024-01-01"
    initial_cash:   float = 1_000_000.0
    cache_dir:      str   = "./data/cache"

    include_sp500:  bool  = True
    include_nasdaq: bool  = True
    include_dow:    bool  = True
    symbols:        Optional[list[str]] = None   # custom list overrides the index toggles
    universe_max_age_days: int = 7

    download:       bool  = True     # False = use cache only (offline)
    warmup_days:    Optional[int] = None   # calendar days of history before start; auto if None
    benchmarks:     list[str] = field(default_factory=lambda: ["SPY", "QQQ"])

    filter:   FilterConfig            = field(default_factory=_default_filter)
    strategy: MACrossoverConfig       = field(default_factory=MACrossoverConfig)
    sim:      SimConfig               = field(default_factory=lambda: SimConfig(slippage_bps=5, commission_per_trade=1.0))
    risk:     LargeUniverseRiskConfig = field(default_factory=_default_risk)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BacktestConfig":
        d = dict(d)
        nested = {
            "filter": FilterConfig, "strategy": MACrossoverConfig,
            "sim": SimConfig, "risk": LargeUniverseRiskConfig,
        }
        for key, klass in nested.items():
            if key in d and isinstance(d[key], dict):
                known = klass.__dataclass_fields__.keys()
                d[key] = klass(**{k: v for k, v in d[key].items() if k in known})
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})

    def effective_warmup_days(self) -> int:
        if self.warmup_days is not None:
            return self.warmup_days
        bars = max(
            self.filter.min_history_days,
            self.filter.adv_lookback,
            self.strategy.slow_period,
            self.risk.corr_lookback,
            self.risk.vol_lookback,
        )
        return int(math.ceil(bars * 365 / 252)) + 30


# ── Result ────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    config:     BacktestConfig
    metrics:    dict
    equity:     pd.DataFrame        # index=date: equity, cash, gross_exposure, open_positions, drawdown
    benchmarks: pd.DataFrame        # index=date: one close column per benchmark
    trades:     pd.DataFrame        # closed-trade ledger
    fills:      pd.DataFrame
    decisions:  pd.DataFrame        # every signal and what the risk manager did with it
    positions:  pd.DataFrame        # open positions at the end
    sector_exposure: dict
    liquidity_rejections: pd.DataFrame
    signal_summary: pd.DataFrame
    meta:       dict = field(default_factory=dict)

    @property
    def rejections(self) -> pd.DataFrame:
        if self.decisions.empty:
            return self.decisions
        return self.decisions[self.decisions["action"] == "rejected"]


ProgressFn = Callable[[int, str, float], None]   # (step index, message, fraction of step done)


class _WarningCollector(logging.Handler):
    def __init__(self, limit: int = 200):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []
        self.limit = limit

    def emit(self, record):
        if len(self.records) < self.limit:
            self.records.append(f"{record.levelname}: {record.name}: {record.getMessage()}")


# ── Pipeline ──────────────────────────────────────────────────

def _universe(cfg: BacktestConfig) -> tuple[list[str], dict[str, str], dict]:
    """Symbols, sector map and universe metadata."""
    info: dict = {}
    if cfg.download:
        table = load_universe(cfg.cache_dir, max_age_days=cfg.universe_max_age_days)
    else:
        import os
        path = os.path.join(cfg.cache_dir, UNIVERSE_FILE)
        table = pd.read_csv(path, parse_dates=["fetched_at"]) if os.path.exists(path) else pd.DataFrame()

    sector_map: dict[str, str] = {}
    if not table.empty:
        sector_map = {
            s: sec for s, sec in zip(table["symbol"], table["sector"])
            if isinstance(sec, str) and sec != "Unknown"
        }
        info["universe_snapshot_date"] = str(pd.Timestamp(table["fetched_at"].max()).date())

    if cfg.symbols:
        symbols = sorted({s.strip().upper() for s in cfg.symbols if s.strip()})
        info["universe_source"] = "custom list"
    else:
        if table.empty:
            raise SystemExit(
                "Universe is empty — universe fetch failed and there is no cached "
                f"{UNIVERSE_FILE}. Install scraping deps: pip install lxml html5lib"
            )
        symbols = select_symbols(table, cfg.include_sp500, cfg.include_nasdaq, cfg.include_dow)
        info["universe_source"] = "index constituents (Wikipedia)"
    return symbols, sector_map, info


def run_backtest(cfg: Optional[BacktestConfig] = None,
                 progress: Optional[ProgressFn] = None) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    t0 = time.time()
    report = progress or (lambda i, msg, frac: None)
    collector = _WarningCollector()
    logging.getLogger().addHandler(collector)
    warnings: list[str] = []

    try:
        warmup = cfg.effective_warmup_days()
        data_start = (pd.Timestamp(cfg.start_date) - pd.Timedelta(days=warmup)).strftime("%Y-%m-%d")

        # ── Step 1: Universe ──────────────────────────────────
        report(0, "Loading universe", 0.0)
        symbols, sector_map, uinfo = _universe(cfg)
        logger.info("Raw universe: %d symbols", len(symbols))
        if not symbols:
            raise SystemExit("Universe is empty.")
        if uinfo.get("universe_source", "").startswith("index"):
            warnings.append(SURVIVORSHIP_WARNING)
        report(0, f"{len(symbols)} symbols", 1.0)

        # ── Step 2: Download & cache ──────────────────────────
        feed = DataFeed(cache_dir=cfg.cache_dir)
        stats = {}
        if cfg.download:
            report(1, f"Downloading {data_start} → {cfg.end_date}", 0.0)
            stats = feed.download(symbols + list(cfg.benchmarks), start=data_start, end=cfg.end_date)
            logger.info("Download stats: %s", stats)
        report(1, "Data ready", 1.0)

        # ── Step 3: Liquidity filter (as of start date) ───────
        report(2, "Filtering", 0.0)
        liq_filter = LiquidityFilter(feed, cfg.filter)
        tradeable = liq_filter.apply(symbols, as_of=cfg.start_date)
        rejection_log = liq_filter.rejection_log()
        logger.info("Tradeable universe: %d symbols", len(tradeable))
        if not tradeable:
            raise SystemExit(
                "No tradeable symbols after liquidity filter. "
                f"Check cached data under {cfg.cache_dir} or relax FilterConfig."
            )
        report(2, f"{len(tradeable)} of {len(symbols)} tradeable", 1.0)

        # ── Step 4: Pre-compute signals ───────────────────────
        report(3, "Computing signals", 0.0)
        prices = feed.load_prices(tradeable, column="close", start=data_start, end=cfg.end_date)
        strategy_model = VectorisedMACrossover(cfg.strategy)
        signals = strategy_model.generate(prices)
        test_signals = signals[signals.index >= pd.Timestamp(cfg.start_date)]
        signal_summary = strategy_model.signal_summary(test_signals)
        report(3, "Signals ready", 1.0)

        # ── Step 5: Wire the engine ───────────────────────────
        engine    = EventEngine()
        portfolio = Portfolio(initial_cash=cfg.initial_cash)
        broker    = SimulatedBroker(engine, cfg.sim)
        risk = LargeUniverseRiskManager(
            portfolio  = portfolio,
            engine     = engine,
            sector_map = sector_map,
            prices_df  = prices,
            config     = cfg.risk,
        )
        strategy = PrecomputedSignalStrategy(signals=signals, symbols=tradeable, engine=engine)

        last_prices: dict[str, float] = {}
        daily: list[dict] = []
        current = {"date": None}

        def snapshot(date) -> None:
            equity = portfolio.total_equity(last_prices)
            gross = sum(
                abs(p.market_value(last_prices.get(s, p.avg_price)))
                for s, p in portfolio.positions.items() if p.quantity != 0
            )
            daily.append({
                "date":           pd.Timestamp(date).normalize(),
                "equity":         equity,
                "cash":           portfolio.cash,
                "gross_exposure": gross / equity if equity else 0.0,
                "open_positions": sum(1 for p in portfolio.positions.values() if p.quantity != 0),
            })
            risk.update_equity(equity)

        def record_daily(event: BarEvent) -> None:
            # Runs FIRST on each bar: when the date changes, yesterday is complete.
            d = event.timestamp.date()
            if current["date"] is not None and d != current["date"]:
                snapshot(current["date"])
            current["date"] = d

        def update_prices(event: BarEvent) -> None:
            last_prices[event.symbol] = event.close
            risk.update_bar(event)

        # Order matters: snapshot → fill yesterday's orders at today's open →
        # update prices → strategy reacts to today's close.
        engine.register(EventType.BAR,    record_daily)
        engine.register(EventType.BAR,    broker.on_bar)
        engine.register(EventType.BAR,    update_prices)
        engine.register(EventType.BAR,    strategy.on_bar)
        engine.register(EventType.SIGNAL, risk.on_signal)
        engine.register(EventType.ORDER,  broker.on_order)
        engine.register(EventType.FILL,   portfolio.on_fill)

        test_dates = prices.index[prices.index >= pd.Timestamp(cfg.start_date)]
        n_dates = max(1, len(test_dates))

        def feed_with_progress():
            seen = 0
            last_date = None
            for bar in feed.bar_generator(tradeable, start=cfg.start_date, end=cfg.end_date):
                d = bar.timestamp.date()
                if d != last_date:
                    last_date = d
                    seen += 1
                    if seen % 5 == 0 or seen == n_dates:
                        report(4, f"{d}", min(1.0, seen / n_dates))
                yield bar

        report(4, "Running", 0.0)
        engine.start(feed_with_progress())
        if current["date"] is not None:
            snapshot(current["date"])

        # ── Step 6: Results ───────────────────────────────────
        report(5, "Building results", 0.0)
        equity = pd.DataFrame(daily).set_index("date") if daily else pd.DataFrame(
            columns=["equity", "cash", "gross_exposure", "open_positions"])
        if not equity.empty:
            # Day-zero point so returns start from initial cash
            first = equity.index[0] - pd.Timedelta(days=1)
            start_row = pd.DataFrame(
                [{"equity": cfg.initial_cash, "cash": cfg.initial_cash,
                  "gross_exposure": 0.0, "open_positions": 0}],
                index=pd.DatetimeIndex([first], name="date"),
            )
            equity = pd.concat([start_row, equity])
            equity["drawdown"] = drawdown_series(equity["equity"])

        bench = pd.DataFrame()
        if cfg.benchmarks:
            bench = feed.load_prices(list(cfg.benchmarks), column="close",
                                     start=cfg.start_date, end=cfg.end_date)
            missing = [b for b in cfg.benchmarks if b not in bench.columns]
            if missing:
                warnings.append(f"No cached data for benchmark(s): {', '.join(missing)}")

        trades = pd.DataFrame([t.to_dict() for t in portfolio.trades])
        fills = pd.DataFrame([{
            "timestamp": f.timestamp, "symbol": f.symbol, "side": f.side.value,
            "quantity": f.quantity, "fill_price": f.fill_price,
            "commission": f.commission, "order_id": f.order_id,
        } for f in portfolio.fill_history])
        decisions = pd.DataFrame(risk.decisions)

        positions = _final_positions(portfolio, last_prices, sector_map, risk, current["date"])
        snap = risk.portfolio_snapshot()

        bench_series = None
        if not bench.empty and cfg.benchmarks and cfg.benchmarks[0] in bench.columns:
            bench_series = bench[cfg.benchmarks[0]]
        metrics = performance_report(
            equity["equity"] if not equity.empty else pd.Series(dtype=float),
            portfolio.pnl_per_trade(),
            benchmark=bench_series,
        )
        metrics["exposure_avg_pct"] = round(float(equity["gross_exposure"].mean()) * 100, 2) if not equity.empty else None
        metrics["total_commission"] = round(float(fills["commission"].sum()), 2) if not fills.empty else 0.0

        unfilled = broker.pending_orders()
        if unfilled:
            warnings.append(f"{len(unfilled)} order(s) created on the last bar were never filled.")
        if snap["halted"]:
            warnings.append("The drawdown halt triggered during the run; new entries stopped.")

        elapsed = time.time() - t0
        report(5, "Done", 1.0)

        meta = {
            "created_at":       datetime.now().isoformat(timespec="seconds"),
            "elapsed_sec":      round(elapsed, 1),
            "data_start":       data_start,
            "warmup_days":      warmup,
            "universe_size":    len(symbols),
            "tradeable_size":   len(tradeable),
            "download_stats":   stats,
            "halted":           snap["halted"],
            "unfilled_orders":  len(unfilled),
            "warnings":         warnings,
            "log_warnings":     collector.records,
            **uinfo,
        }

        return BacktestResult(
            config=cfg, metrics=metrics, equity=equity, benchmarks=bench,
            trades=trades, fills=fills, decisions=decisions, positions=positions,
            sector_exposure=snap["sector_exposure"],
            liquidity_rejections=rejection_log,
            signal_summary=signal_summary.reset_index() if not signal_summary.empty else signal_summary,
            meta=meta,
        )
    finally:
        logging.getLogger().removeHandler(collector)


def _final_positions(portfolio, last_prices, sector_map, risk, last_date) -> pd.DataFrame:
    equity = portfolio.total_equity(last_prices)
    rows = []
    for s, p in portfolio.positions.items():
        if p.quantity == 0:
            continue
        price = last_prices.get(s, p.avg_price)
        mv = p.market_value(price)
        rows.append({
            "symbol":          s,
            "sector":          sector_map.get(s, "Unknown"),
            "quantity":        p.quantity,
            "avg_price":       p.avg_price,
            "last_price":      price,
            "market_value":    mv,
            "weight":          mv / equity if equity else 0.0,
            "unrealised_pnl":  p.unrealised_pnl(price),
            "unrealised_pct":  price / p.avg_price - 1 if p.avg_price else 0.0,
            "opened_at":       p.opened_at,
            "annual_vol":      risk._annual_vol(s, last_date),
            "target_weight":   risk.target_notional(s, equity, 1.0, last_date) / equity if equity else None,
        })
    df = pd.DataFrame(rows)
    return df.sort_values("market_value", ascending=False).reset_index(drop=True) if not df.empty else df
