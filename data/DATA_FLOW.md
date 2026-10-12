# Data package flow

This package contains the market data ingestion, caching, and universe loading logic used by the backtester.

## Purpose

The `data` package provides:
- price download and parquet cache (`DataFeed`),
- universe loading from Wikipedia (`load_universe`, `build_universe_table`),
- liquidity filters (`FilterConfig`, `LiquidityFilter`),
- coverage bookkeeping for incremental refreshes.

## High-level flow

```text
Universe request / backtest config
    ↓
load_universe(...)
    ├─ fetch Wikipedia constituent tables
    ├─ save to data/cache/_universe.csv
    └─ return DataFrame snapshot

Backtest run
    ↓
DataFeed.download(symbols, start, end)
    ├─ yfinance.download(...)
    ├─ normalize OHLCV
    ├─ save parquet cache files
    └─ update _coverage.json

Later use
    ↓
DataFeed.load_prices(...)
    ↓
wide DataFrame indexed by date and symbols
```

## Main classes and functions

### `DataFeed`

File: `data/feed.py`

Key methods:
- `DataFeed.__init__(cache_dir)`
  - initialize the cache directory.
- `DataFeed.download(symbols, start, end, interval="1d", force=False, batch_size=...)`
  - fetch missing OHLCV data and save parquet files.
- `DataFeed._covers(symbol, start, end, coverage)`
  - check whether cached data already spans the requested range.
- `DataFeed._save(symbol, df)`
  - persist one symbol's data to parquet.
- `DataFeed._load(symbol)`
  - read cached dataframe for one symbol.
- `DataFeed.load_prices(symbols, start=None, end=None)`
  - return a wide price table for strategy generation.
- `DataFeed.bar_generator(symbols, start=None, end=None)`
  - yield `BarEvent` instances for the event engine.
- `DataFeed.coverage_report(symbols=None)`
  - show per-symbol cache coverage and historical range.

Purpose:
- manage all cached market data for the project.
- prevent redundant re-downloads by tracking requested ranges in `data/cache/_coverage.json`.

### Universe loaders

File: `data/universe.py`

Key functions:
- `_read_html(url)`
  - fetch a Wikipedia page with a browser-like headers and parse HTML.
- `get_sp500()`
  - fetch S&P 500 symbols.
- `get_nasdaq100()`
  - fetch NASDAQ-100 symbols.
- `get_dow30()`
  - fetch Dow 30 symbols.
- `get_full_universe(...)`
  - combine all index constituents.
- `get_sp500_sector_map()`, `get_nasdaq100_sector_map()`, `get_sector_map()`
  - map symbols to sectors.
- `build_universe_table(...)`
  - create a table with symbol, sector, and index flags.
- `load_universe(cache_dir, max_age_days, refresh=False)`
  - return the cached or refreshed snapshot.
- `select_symbols(table, ...)`
  - choose active symbols for a run.

Purpose:
- fetch the current index universe and cache it for reproducibility.
- avoid repeated network fetches if the snapshot is still fresh.

### Liquidity filtering

File: `data/filters.py`

Key classes/functions:
- `FilterConfig`
  - configuration for ADV, price, and history minimum thresholds.
- `LiquidityFilter`
  - applies the rules on the price dataset as of the backtest start date.

Purpose:
- remove illiquid or low-quality symbols before strategy evaluation.
- uses a point-in-time filter to avoid look-ahead bias.

## Typical data pipeline

```text
Universe config
    ↓
load_universe()
    ↓
DataFrame of constituents + sectors
    ↓
DataFeed.download()
    ↓
cache parquet files
    ↓
DataFeed.load_prices()
    ↓
strategies consume wide price DataFrame
```

## Notes

- Data is cached under `data/cache/`.
- coverage metadata is stored in `data/cache/_coverage.json`.
- the universe snapshot is saved as `_universe.csv` and a dated version as `_universe_YYYYMMDD.csv`.
- the app falls back to cached data when the refresh fails.

## Summary

The `data` package is the input layer of the system: it loads the universe, downloads price history, normalizes it, and makes it available to the strategy and backtest engine.
