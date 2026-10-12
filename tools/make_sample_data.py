"""
tools/make_sample_data.py
-------------------------
Writes a SYNTHETIC price cache so the backtest and UI can be tried
without internet access (no Yahoo / Wikipedia needed).

    python tools/make_sample_data.py --cache-dir ./data/sample_cache
    python run_backtest_large.py --offline   (after pointing CACHE_DIR at it)

Prices are random (a market factor + sector factor + noise). Never mix
this cache with the real one: it uses made-up tickers (SYN001...).
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.universe import UNIVERSE_FILE  # noqa: E402

SECTORS = [
    "Information Technology", "Health Care", "Financials", "Consumer Discretionary",
    "Industrials", "Communication Services", "Consumer Staples", "Energy",
    "Utilities", "Real Estate", "Materials",
]


def make(cache_dir: str, n_symbols: int, start: str, end: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end, inclusive="left")
    n = len(dates)
    os.makedirs(cache_dir, exist_ok=True)

    market = rng.normal(0.0004, 0.010, n)
    sector_f = {s: rng.normal(0.0001, 0.007, n) for s in SECTORS}
    coverage, rows = {}, []

    def write(symbol, rets, base_price, base_volume):
        close = base_price * np.exp(np.cumsum(rets))
        gap = rng.normal(0, 0.003, n)
        open_ = close * np.exp(-rets / 2 + gap)
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
        volume = base_volume * np.exp(rng.normal(0, 0.3, n))
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=pd.DatetimeIndex(dates, name="timestamp").as_unit("ns"),
        )
        df.to_parquet(os.path.join(cache_dir, f"{symbol}.parquet"))
        coverage[symbol] = {"start": start, "end": end}

    for i in range(n_symbols):
        symbol = f"SYN{i + 1:03d}"
        sector = SECTORS[i % len(SECTORS)]
        beta = rng.uniform(0.6, 1.4)
        idio = rng.uniform(0.008, 0.025)
        rets = beta * market + sector_f[sector] + rng.normal(0, idio, n)
        price = rng.uniform(15, 400)
        # a few illiquid / cheap names so the liquidity filter has work to do
        vol_base = 2e4 if i % 17 == 0 else rng.uniform(2e5, 5e6)
        if i % 23 == 0:
            price = 3.0
        write(symbol, rets, price, vol_base)
        rows.append({
            "symbol": symbol, "sector": sector,
            "sp500": i % 5 != 0, "nasdaq100": i % 3 == 0, "dow30": i % 10 == 0,
            "fetched_at": pd.Timestamp.now().normalize(),
        })

    write("SPY", market, 380.0, 8e7)
    write("QQQ", 1.2 * market + sector_f["Information Technology"] * 0.5, 300.0, 5e7)

    pd.DataFrame(rows).to_csv(os.path.join(cache_dir, UNIVERSE_FILE), index=False)
    with open(os.path.join(cache_dir, "_coverage.json"), "w") as f:
        json.dump(coverage, f, indent=1)
    print(f"Wrote {n_symbols} synthetic symbols + SPY/QQQ to {cache_dir} ({n} days).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache-dir", default="./data/sample_cache")
    p.add_argument("--symbols", type=int, default=120)
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default="2024-01-01")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    make(a.cache_dir, a.symbols, a.start, a.end, a.seed)
