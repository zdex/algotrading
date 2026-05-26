"""
run_backtest_large.py
---------------------
Full pipeline for backtesting across S&P 500 + NASDAQ + Dow Jones.

Pipeline
--------
1. Fetch universe  (~550 symbols)
2. Download & cache OHLCV data (Parquet)
3. Apply liquidity filter  (~400 symbols remain)
4. Pre-compute vectorised signals (all symbols × all dates at once)
5. Run event-driven engine with PrecomputedSignalStrategy
6. Print performance report

Run with:
    pip install yfinance pandas pyarrow lxml html5lib
    python run_backtest_large.py
"""

import logging
import time

from data.universe   import get_full_universe, get_sp500_sector_map
from data.feed       import DataFeed
from data.filters    import LiquidityFilter, FilterConfig
from core.engine     import EventEngine
from core.events     import EventType, BarEvent
from core.portfolio  import Portfolio
from core.risk_large import LargeUniverseRiskManager, LargeUniverseRiskConfig
from execution.adapters.simulated import SimulatedBroker, SimConfig
from strategy.examples.ma_crossover_vectorised import (
    VectorisedMACrossover, MACrossoverConfig, PrecomputedSignalStrategy,
)
from backtester.metrics import summary_report

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger("backtest_large")


# ── Global config ─────────────────────────────────────────────

START_DATE    = "2021-01-01"
END_DATE      = "2024-01-01"
INITIAL_CASH  = 1_000_000.0     # $1M — realistic for this universe size
CACHE_DIR     = "./data/cache"


# ── Pipeline ──────────────────────────────────────────────────

def run():
    t0 = time.time()

    # ── Step 1: Universe ──────────────────────────────────────
    logger.info("=== STEP 1: Fetching universe ===")
    symbols = get_full_universe(
        include_sp500  = True,
        include_nasdaq = True,
        include_dow    = True,
    )
    logger.info("Raw universe: %d symbols", len(symbols))
    if not symbols:
        raise SystemExit(
            "Universe is empty — universe fetch failed. "
            "Install scraping deps: pip install lxml html5lib"
        )

    sector_map = get_sp500_sector_map()

    # ── Step 2: Download & cache ──────────────────────────────
    logger.info("=== STEP 2: Downloading data ===")
    feed = DataFeed(cache_dir=CACHE_DIR)
    stats = feed.download(symbols, start=START_DATE, end=END_DATE)
    logger.info("Download stats: %s", stats)

    # ── Step 3: Liquidity filter ──────────────────────────────
    logger.info("=== STEP 3: Applying liquidity filter ===")
    liq_filter = LiquidityFilter(
        feed,
        FilterConfig(
            min_adv_usd      = 5_000_000,   # $5M ADV for a $1M portfolio
            min_price        = 5.0,
            min_history_days = 400,
        ),
    )
    tradeable = liq_filter.apply(symbols)
    logger.info("Tradeable universe: %d symbols", len(tradeable))
    if not tradeable:
        raise SystemExit(
            "No tradeable symbols after liquidity filter. "
            "Check cached data under ./data/cache or relax FilterConfig."
        )

    rejection_log = liq_filter.rejection_log()
    top_reasons   = rejection_log["reason"].value_counts().head(5)
    logger.info("Top rejection reasons:\n%s", top_reasons.to_string())

    # ── Step 4: Pre-compute signals ───────────────────────────
    logger.info("=== STEP 4: Generating vectorised signals ===")
    prices = feed.load_prices(tradeable, column="close")

    strategy_model = VectorisedMACrossover(
        MACrossoverConfig(fast_period=10, slow_period=30, allow_short=False)
    )
    signals = strategy_model.generate(prices)

    summary = strategy_model.signal_summary(signals)
    logger.info(
        "Signal summary:\n%s",
        summary.describe().to_string()
    )

    # ── Step 5: Wire the engine ───────────────────────────────
    logger.info("=== STEP 5: Running backtest engine ===")
    engine    = EventEngine()
    portfolio = Portfolio(initial_cash=INITIAL_CASH)
    broker    = SimulatedBroker(
        engine,
        SimConfig(slippage_bps=5, commission_per_trade=1.0)
    )
    risk = LargeUniverseRiskManager(
        portfolio  = portfolio,
        engine     = engine,
        sector_map = sector_map,
        prices_df  = prices,
        config     = LargeUniverseRiskConfig(
            max_position_pct   = 0.02,
            default_order_pct  = 0.01,
            max_open_positions = 50,
            max_sector_pct     = 0.25,
            max_correlation    = 0.85,
            use_vol_targeting  = True,
            target_annual_vol  = 0.15,
        ),
    )
    strategy = PrecomputedSignalStrategy(
        signals = signals,
        symbols = tradeable,
        engine  = engine,
    )

    # ── Register handlers ─────────────────────────────────────
    engine.register(EventType.BAR,    strategy.on_bar)
    engine.register(EventType.BAR,    _make_price_updater(broker, risk))
    engine.register(EventType.SIGNAL, risk.on_signal)
    engine.register(EventType.ORDER,  broker.on_order)
    engine.register(EventType.FILL,   portfolio.on_fill)

    # ── Track equity curve ────────────────────────────────────
    equity_curve: list[float] = [INITIAL_CASH]
    last_prices:  dict[str, float] = {}

    def track_equity(event: BarEvent):
        last_prices[event.symbol] = event.close
        equity_curve.append(portfolio.total_equity(last_prices))

    engine.register(EventType.BAR, track_equity)

    # ── Run ───────────────────────────────────────────────────
    bar_feed = feed.bar_generator(tradeable)
    engine.start(bar_feed)

    elapsed = time.time() - t0

    # ── Step 6: Results ───────────────────────────────────────
    logger.info("=== STEP 6: Results ===")

    fills = portfolio.fill_history
    pnl_per_trade: list[float] = []
    for i in range(0, len(fills) - 1, 2):
        entry, exit_ = fills[i], fills[i + 1]
        pnl = (exit_.fill_price - entry.fill_price) * entry.quantity
        pnl_per_trade.append(pnl)

    print("\n" + "═" * 60)
    print("  LARGE UNIVERSE BACKTEST RESULTS")
    print("═" * 60)

    report = summary_report(equity_curve, pnl_per_trade)
    for k, v in report.items():
        print(f"  {k:<28} {v}")

    print("─" * 60)
    snapshot = risk.portfolio_snapshot()
    print(f"  Final open positions:        {snapshot['open_positions']}")
    print(f"  Final gross exposure:        {snapshot['gross_exposure']:.1%}")
    print(f"  Elapsed time:                {elapsed:.1f}s")
    print("─" * 60)

    print("\n  Sector Exposure (final):")
    for sector, pct in sorted(
        snapshot["sector_exposure"].items(), key=lambda x: -x[1]
    ):
        bar = "█" * int(pct * 40)
        print(f"    {sector:<35} {pct:5.1%}  {bar}")

    print("═" * 60)
    print(portfolio.summary(last_prices))


# ── Helper ────────────────────────────────────────────────────

def _make_price_updater(broker, risk):
    def handler(event: BarEvent):
        broker.update_price(event.symbol, event.close)
        risk.update_price(event.symbol, event.close)
    return handler


if __name__ == "__main__":
    run()
