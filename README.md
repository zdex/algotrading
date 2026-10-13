# algotrading

Event-driven algorithmic trading system (Python): large-universe backtesting,
risk management, IBKR paper trading, plus a Streamlit UI.
# Analysis
Fundamental Analysis - 
   company analysis
   results analysis
   Company news analysis
Technical Analysis, sentiment analysis
Social media, news, web,

Chatbot where user can upload documents and ask questions about the document, about his own porfolio, his own historical 
trades, ask about company news.
Agents ?

## Quick start (Windows PowerShell)

```powershell
cd C:\Users\gmahe\Gaurav_folder\Gaurav_study\Investments\Projects\algotrading
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip # to upgrade pip
pip install -r requirements.txt

# 1. Run the large-universe backtest (downloads data the first time, several minutes)
python run_backtest_large.py

# 2. Open the UI (http://localhost:8501)
streamlit run ui/app.py
```

To try the UI with no internet access, generate synthetic data first and pick
**Sample data** in the sidebar:

```powershell
python tools/make_sample_data.py      # writes data/sample_cache/
streamlit run ui/app.py
```

Run the tests with `pytest -q`.

## UI pages

| Page | What it shows |
|------|---------------|
| **Command Center** | Status (paper mode, data freshness, saved runs), KPIs, equity vs SPY/QQQ, drawdown, open positions, sector exposure vs cap, latest signals and what risk did with them, signals blocked by risk, recent trades |
| **Backtest Lab** | Every setting from `run_backtest_large.py` as a form (dates, universe or custom symbols, MA periods, liquidity filter, risk limits, vol targeting, costs). Runs with step-by-step progress and saves to `results/` |
| **Backtest Results** | One run in full (performance, monthly returns, rolling Sharpe, trades with filters, every risk decision, positions, config and warnings, CSV downloads) and a compare-runs tab |
| **Strategy Explorer** | Candlesticks with MAs and fill markers for one symbol, signal vs buy & hold, parameter sensitivity grid |
| **Risk** | Sector exposure vs cap, gross exposure and position count over time, vol-target sizing per position, correlation heatmap of holdings, blocked signals by reason |
| **Universe & Data** | Constituents with sectors and index membership, cache coverage per symbol, buttons to refresh the universe and download prices |
| **Phase 1 Validation**, **Live Trading** | Placeholders: `run_phase1.py` and the Phase 2 files weren't part of this upload |

## Project structure

```
core/         engine, events, portfolio (with closed-trade ledger), risk, risk_large
data/         feed (Parquet cache), filters (liquidity), universe (Wikipedia + dated snapshot)
strategy/     base class, MA crossover (event-driven and vectorised)
execution/    adapters/simulated.py (next-open fill model)
backtester/   metrics, runner (pipeline → BacktestResult), results_store (save/load runs)
ui/           app.py, views/ (one file per page), components/ (charts, tables, theme, state)
tools/        make_sample_data.py
tests/        regression tests for the fixes below
results/      saved backtest runs (git-ignored)
```

`run_backtest_large.py` is now a thin CLI around `backtester.runner.run_backtest()`,
which returns a `BacktestResult` instead of printing. Use `--offline` to skip downloads.

## Correctness fixes in this version

Backtest numbers **will change** compared with the previous code; most of these
made the old results look better than they really were.

1. **Look-ahead in risk sizing and correlation.** `risk_large` computed volatility and
   correlation from the last 20/60 days of the *whole dataset*. It now uses only
   prices up to the signal's bar.
2. **Look-ahead in the liquidity filter.** It used the last close and last 20 days of
   volume in the cache. It now runs as of the backtest start date (data is downloaded
   with enough warm-up history before the start).
3. **Same-bar fills.** The simulated broker filled at the close the signal was computed
   from. It now fills at the **next bar's open** (`SimConfig.fill_timing="next_open"`).
   The risk manager counts its own unfilled orders, so many signals on one day can't
   exceed the position, exposure or sector limits.
4. **Vol targeting had no effect.** With `equity × 15% / vol` capped at 2%, every position
   ended up at 2%. The new default `vol_target_mode="portfolio"` treats the 15% as a
   portfolio target split across `max_open_positions` slots (a 30%-vol stock gets about
   1%). Set `vol_target_mode="per_position"` for the old behaviour. **Gross exposure is
   lower as a result**; raise `target_annual_vol` if you want more deployed.
5. **Per-trade P&L.** The scripts paired consecutive fills, which mixes symbols. Trades
   now come from `Portfolio.trades`, recorded per symbol with entry/exit time and
   commissions. Reversing a position through zero now resets the average price.
6. **Equity curve and metrics.** The curve had one point per bar (~400 per day), which
   broke CAGR and Sharpe. It's now one dated point per trading day, and
   `performance_report()` adds Sortino, Calmar, volatility, alpha/beta vs SPY.
7. **Timestamps.** Signals, orders and fills used wall-clock time. They now carry the
   bar's market time.
8. **Risk decisions are logged.** Every signal records approved / rejected (with the
   check, value and limit) / ignored, so the UI can show what was blocked and why.
9. **Drawdown halt** now measures from peak equity (`drawdown_from_peak=True`; set False
   for the old "loss from starting cash"). Exits are still allowed after a halt.
10. **Sectors.** NASDAQ-100 names outside the S&P 500 now get sectors from the NASDAQ-100
    table, and any remaining unknown names share an "Unknown" bucket under the sector cap.
11. **Cache refresh.** `DataFeed.download()` re-fetches a symbol when its cached range
    doesn't cover the requested dates (tracked in `data/cache/_coverage.json`).
    `load_prices()` and `bar_generator()` take `start`/`end`.
12. **Small fixes.** The event-driven MA crossover no longer errors on the first bar
    after warm-up, and same-direction repeat signals are ignored instead of adding to
    a position.

**Not fixed: survivorship bias.** The universe is today's index constituents. Fixing that
needs historical constituent data; the UI shows a warning on every run.

## Compatibility

Public interfaces are unchanged or extended with optional arguments (`summary_report`,
`LargeUniverseRiskManager(...)`, `SimulatedBroker`, `DataFeed.download`, `FilterConfig`,
`Portfolio.fill_history`). Scripts that only call `broker.update_price()` and never
register `broker.on_bar` still work: the broker falls back to filling at the close and
logs a warning. `run_phase1.py` and the Phase 2 files weren't in this upload, so they
haven't been tested against these changes.
