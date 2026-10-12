# Backtester flow: UI click to final result

This document describes the full technical flow when the user clicks the UI button `Run backtest` in `ui/views/backtest_lab.py`.

## Entry point from the UI

The UI creates a `BacktestConfig` and then calls:

```python
result = run_backtest(cfg, progress)
```

Defined in:
- `ui/views/backtest_lab.py`
- imported from:
  - `from backtester.runner import STEPS, BacktestConfig, run_backtest`

## The function actually called

`backtester.runner.run_backtest(cfg, progress=None) -> BacktestResult`

Purpose:
- orchestrates the entire historical backtest pipeline,
- resolves the universe,
- loads cached data or downloads it,
- filters symbols,
- generates signals,
- runs the event engine,
- applies risk checks and fills,
- computes portfolio metrics,
- returns a `BacktestResult` object for the UI.

## Full flow diagram

```text
UI / Streamlit
│
├─ `ui/views/backtest_lab.py`
│   └─ `st.form_submit_button("Run backtest")`
│       ↓
│   └─ `cfg = BacktestConfig(...)`
│       ↓
│   └─ `result = run_backtest(cfg, progress)`
│       Purpose: launch the whole backtest pipeline
│
└─ `save_result(result, state.results_dir())`
    Purpose: persist results to `results/` and display KPIs on the UI

────────────────────────────────────────────────────────────────────
`backtester.runner`
│
├─ `BacktestConfig`
│   Purpose: central configuration object for the run.
│   Fields include:
│   - dates (`start_date`, `end_date`)
│   - cash (`initial_cash`)
│   - universe settings (`include_sp500`, `include_nasdaq`, `include_dow`, `symbols`)
│   - strategy config (`strategy`)
│   - filter config (`filter`)
│   - risk config (`risk`)
│   - sim config (`sim`)
│   - cache dir and download mode
│
├─ `run_backtest(cfg, progress=None)`
│   Purpose: high-level orchestration of the full pipeline
│   ↓
│   ├─ `_universe(cfg) -> (symbols, sector_map, info)`
│   │   Purpose: determine the investable symbol list for the run.
│   │   ↓
│   │   ├─ `load_universe(cache_dir, max_age_days, refresh=False)`
│   │   │   Purpose: read the cached universe snapshot or fetch it if stale/missing.
│   │   │   ↓
│   │   │   ├─ `build_universe_table()`
│   │   │   │   Purpose: build a dated DataFrame of symbol, sector, and index flags.
│   │   │   │   ├─ `get_sp500()`
│   │   │   │   │   Purpose: fetch S&P 500 constituents from Wikipedia.
│   │   │   │   ├─ `get_nasdaq100()`
│   │   │   │   │   Purpose: fetch NASDAQ-100 constituents from Wikipedia.
│   │   │   │   └─ `get_dow30()`
│   │   │   │       Purpose: fetch Dow 30 constituents from Wikipedia.
│   │   │   └─ `select_symbols(table, ...)`
│   │   │       Purpose: return only selected index constituents.
│   │   │
│   │   └─ if universe is empty and no cached file exists -> raises `SystemExit`
│   │       Message: "Universe is empty — universe fetch failed and there is no cached _universe.csv. Install scraping deps: pip install lxml html5lib"
│   │
│   ├─ `DataFeed(cache_dir=cfg.cache_dir)`
│   │   Purpose: manage historical OHLCV price download and cache.
│   │   ↓
│   │   ├─ `feed.download(symbols, start, end)`
│   │   │   Purpose: download missing price files to parquet cache.
│   │   │   Uses `yfinance.download()` under the hood.
│   │   │
│   │   ├─ `feed.load_prices(symbols, start, end)`
│   │   │   Purpose: read a wide price matrix for strategy signals.
│   │   │
│   │   └─ `feed.bar_generator(symbols, start, end)`
│   │       Purpose: yield each daily bar as a `BarEvent` to the event engine.
│   │
│   ├─ `LiquidityFilter` / `FilterConfig`
│   │   Purpose: remove names that fail min ADV, min price, or minimum history requirements.
│   │   Applied as-of the start date to avoid look-ahead bias.
│   │
│   ├─ `VectorisedMACrossover.generate(prices_df)`
│   │   Purpose: compute signal matrices for every symbol across all dates.
│   │   Uses rolling SMA crossovers:
│   │   - fast MA > slow MA => LONG
│   │   - fast MA < slow MA => SHORT/FLAT depending on config
│   │   - otherwise carry last state forward
│   │
│   ├─ `PrecomputedSignalStrategy.calculate(event: BarEvent)`
│   │   Purpose: convert the precomputed signal matrix into `SignalEvent`s during engine replay.
│   │   Emits only when a symbol's signal changes.
│   │
│   ├─ `EventEngine.start(data_feed)`
│   │   Purpose: process the market-event stream and dispatch events.
│   │   ↓
│   │   ├─ `engine.register(EventType.BAR, handler)`
│   │   │   Purpose: attach handlers for bars and downstream actions.
│   │   │
│   │   ├─ `engine.put(event)`
│   │   │   Purpose: push an event onto the queue.
│   │   │
│   │   ├─ `engine._dispatch(event)`
│   │   │   Purpose: call all registered handlers for that event.
│   │   │
│   │   └─ event loop drives the full path: market data → signals → risk → orders → fills
│   │
│   ├─ `LargeUniverseRiskManager.on_signal(event: SignalEvent)`
│   │   Purpose: risk gate for every candidate signal.
│   │   Checks:
│   │   - drawdown halt
│   │   - already-held position
│   │   - max open positions
│   │   - gross exposure
│   │   - sector concentration
│   │   - correlation threshold
│   │   - volatility-target sizing
│   │   ↓
│   │   ├─ `LargeUniverseRiskManager._size_position(...)`
│   │   │   Purpose: size order correctly with volatility targeting and max position cap.
│   │   │
│   │   ├─ `LargeUniverseRiskManager._send(symbol, side, qty, ts)`
│   │   │   Purpose: emit an `OrderEvent` only when checks pass.
│   │   │
│   │   └─ `LargeUniverseRiskManager.decisions`
│   │       Purpose: log every approved/rejected/ignored signal for UI reporting.
│   │
│   ├─ `SimulatedBroker.on_order(event: OrderEvent)`
│   │   Purpose: receive valid orders and create paper fills.
│   │   ↓
│   │   ├─ `SimulatedBroker.on_bar(event: BarEvent)`
│   │   │   Purpose: fill queued orders at the next bar open.
│   │   │
│   │   └─ `SimulatedBroker._fill(order, price, ts)`
│   │       Purpose: create `FillEvent` with slippage and commission.
│   │
│   ├─ `Portfolio.on_fill(event: FillEvent)`
│   │   Purpose: update cash, open positions, closed trades, and per-trade P&L.
│   │   ↓
│   │   ├─ `Position.update(fill)`
│   │   │   Purpose: update the position ledger; closes/reversals produce `Trade` objects.
│   │   │
│   │   └─ `Portfolio.trades`
│   │       Purpose: root truth for trade-level P&L and UI trade log.
│   │
│   ├─ `performance_report(...)`
│   │   Purpose: calculate Sharpe, Sortino, CAGR, drawdown, volatility, and benchmark alpha/beta.
│   │
│   ├─ `drawdown_series(...)`
│   │   Purpose: build the drawdown curve from equity values.
│   │
│   └─ `BacktestResult(...)`
│       Purpose: package all outputs into one object.
│       Contains:
│       - `metrics`
│       - `equity`
│       - `benchmarks`
│       - `trades`
│       - `fills`
│       - `decisions`
│       - `positions`
│       - `sector_exposure`
│       - `liquidity_rejections`
│       - `signal_summary`
│       - `meta`
│
└─ `return result`
    Purpose: send the final result back to the UI for display and saving.
```

## Key class relationships

```text
BacktestConfig
  ├─ strategy : MACrossoverConfig
  ├─ filter  : FilterConfig
  ├─ risk    : LargeUniverseRiskConfig
  ├─ sim     : SimConfig
  └─ runs via `run_backtest()`

run_backtest()
  ├─ _universe()
  ├─ DataFeed
  ├─ LiquidityFilter
  ├─ VectorisedMACrossover
  ├─ PrecomputedSignalStrategy
  ├─ EventEngine
  ├─ LargeUniverseRiskManager
  ├─ SimulatedBroker
  ├─ Portfolio
  └─ BacktestResult
```

## Short version

The button click triggers:

```python
run_backtest(BacktestConfig(...), progress)
```

Then the pipeline is:

```text
Universe -> Data -> Filter -> Signals -> Event Engine -> Risk -> Orders -> Fills -> Portfolio -> Metrics -> Result
```

This is the path implemented by the `backtester.runner` orchestration layer.
