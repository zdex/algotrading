"""
run_backtest_large.py
---------------------
Full pipeline for backtesting across S&P 500 + NASDAQ + Dow Jones.

The pipeline itself now lives in backtester/runner.py so the Streamlit UI
can run it too. This script runs it with the settings below, prints the
report and saves the run to ./results/ (where the UI picks it up).

Run with:
    pip install -r requirements.txt
    python run_backtest_large.py
    python run_backtest_large.py --offline     # cache only, no downloads
"""

import argparse
import logging

from backtester.runner import BacktestConfig, run_backtest
from backtester.results_store import save_result
from core.risk_large import LargeUniverseRiskConfig
from data.filters import FilterConfig
from execution.adapters.simulated import SimConfig
from strategy.examples.ma_crossover_vectorised import MACrossoverConfig

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


def build_config(offline: bool = False) -> BacktestConfig:
    return BacktestConfig(
        name         = "cli",
        start_date   = START_DATE,
        end_date     = END_DATE,
        initial_cash = INITIAL_CASH,
        cache_dir    = CACHE_DIR,
        download     = not offline,
        filter = FilterConfig(
            min_adv_usd      = 5_000_000,   # $5M ADV for a $1M portfolio
            min_price        = 5.0,
            min_history_days = 400,
        ),
        strategy = MACrossoverConfig(fast_period=10, slow_period=30, allow_short=False),
        sim      = SimConfig(slippage_bps=5, commission_per_trade=1.0),
        risk     = LargeUniverseRiskConfig(
            max_position_pct   = 0.02,
            default_order_pct  = 0.01,
            max_open_positions = 50,
            max_sector_pct     = 0.25,
            max_correlation    = 0.85,
            use_vol_targeting  = True,
            target_annual_vol  = 0.15,
        ),
    )


def run(offline: bool = False):
    result = run_backtest(build_config(offline))
    run_id = save_result(result)

    print("\n" + "═" * 60)
    print("  LARGE UNIVERSE BACKTEST RESULTS")
    print("═" * 60)
    for k, v in result.metrics.items():
        print(f"  {k:<28} {v}")

    print("─" * 60)
    print(f"  Universe / tradeable:        {result.meta['universe_size']} / {result.meta['tradeable_size']}")
    print(f"  Final open positions:        {len(result.positions)}")
    if not result.equity.empty:
        print(f"  Final gross exposure:        {result.equity['gross_exposure'].iloc[-1]:.1%}")
    print(f"  Risk rejections:             {len(result.rejections)}")
    print(f"  Elapsed time:                {result.meta['elapsed_sec']:.1f}s")
    print("─" * 60)

    print("\n  Sector Exposure (final):")
    for sector, pct in sorted(result.sector_exposure.items(), key=lambda x: -x[1]):
        bar = "█" * int(pct * 40)
        print(f"    {sector:<35} {pct:5.1%}  {bar}")

    for w in result.meta["warnings"]:
        print(f"\n  ⚠ {w}")
    print("═" * 60)
    print(f"  Saved as results/{run_id}  (open it in the UI: streamlit run ui/app.py)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="use cached data only")
    args = parser.parse_args()
    run(offline=args.offline)
