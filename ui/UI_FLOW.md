# UI package flow

This package contains the Streamlit interface used to configure and launch backtests.

## Purpose

The `ui` package provides the app shell and page-level views for:
- home,
- backtest lab,
- results,
- risk,
- strategy explorer,
- universe and data,
- live trading placeholders.

## Main entry point

File: `ui/app.py`

Purpose:
- create the Streamlit app,
- register navigation/pages,
- load the selected page.

## Page flow

Typical page wiring:

```text
ui/app.py
    ↓
page selection / nav
    ↓
ui/views/*.py
```

Examples:
- `ui/views/backtest_lab.py`
- `ui/views/results.py`
- `ui/views/universe_data.py`
- `ui/views/risk.py`
- `ui/views/home.py`

## Backtest Lab workflow

File: `ui/views/backtest_lab.py`

Main flow:

```text
user fills form
    ↓
BacktestConfig(...)
    ↓
run_backtest(cfg, progress)
    ↓
show status bar / progress messages
    ↓
save_result(result, state.results_dir())
    ↓
show KPI summary and result page link
```

Key UI actions:
- `st.form_submit_button("Run backtest")`
  - user triggers backtest execution.
- `progress(i, msg, frac)`
  - updates the status bar based on `STEPS` in `backtester.runner`.
- `save_result(result, ...)`
  - persists the run to the `results/` directory.

## State helpers

File: `ui/components/state.py`

Purpose:
- manage cached state for:
  - cache directory,
  - universe table,
  - coverage,
  - saved runs,
  - selected result.

## Universe/data page

File: `ui/views/universe_data.py`

Purpose:
- show the current universe snapshot,
- show sector counts,
- let the user refresh the universe,
- show price cache coverage,
- allow downloading data from Yahoo Finance.

## Result display

Files:
- `ui/views/results.py`
- `ui/components/widgets.py`
- `ui/components/charts.py`

Purpose:
- render metrics, trade tables, equity curves, risk decisions, and charts after a run finishes.

## Market Monitor

Section in the sidebar, backed by `market_monitor/` (catalog, scoring, workflow) and `ui/market_monitor/` (page layout).

Subsections: Monitor Home, Global Macro, Markets, Corporate Events, Risk Alerts, Sector Rotation, Portfolio Health, Upcoming Catalysts, Decision Log, Event Explorer, Watchlists, Data Sources, Settings.

The feed is a simulated batch. Category 18 is owned by Markets. The Decision Log links to events and keeps an append-only audit trail. See `market_monitor/README.md`.

## Summary

The `ui` package is the front-end orchestration layer: it builds config, calls the `backtester.runner.run_backtest()` function, displays progress, and then renders the final metrics and artifacts stored in `results/`.
