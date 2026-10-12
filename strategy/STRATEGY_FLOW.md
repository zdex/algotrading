# Strategy package flow

This package contains the signal-generation logic used by the backtester.

## Purpose

The `strategy` package provides the trading logic that turns price data into trade signals.

Main strategy in this project:
- `VectorisedMACrossover` in `strategy/examples/ma_crossover_vectorised.py`

## High-level flow

```text
Price DataFrame
    ↓
VectorisedMACrossover.generate(prices)
    ↓
signal matrix (LONG / SHORT / FLAT)
    ↓
PrecomputedSignalStrategy.calculate(event)
    ↓
SignalEvent
    ↓
LargeUniverseRiskManager.on_signal(event)
```

## Main classes and functions

### `MACrossoverConfig`

File: `strategy/examples/ma_crossover_vectorised.py`

Purpose:
- configure the moving-average crossover strategy.
- fields include:
  - `fast_period`
  - `slow_period`
  - `allow_short`

### `VectorisedMACrossover`

Key methods:
- `VectorisedMACrossover.__init__(config)`
  - store the MA configuration.
- `VectorisedMACrossover.generate(prices)`
  - compute crossovers for all symbols in a wide DataFrame.
- `VectorisedMACrossover._propagate(signals)`
  - carry the last active signal forward.
- `VectorisedMACrossover.signal_summary(signals)`
  - summarize signal counts per symbol.

Purpose:
- generate signals across the entire universe in a vectorized way.
- faster than discrete per-symbol loops for large datasets.

### `PrecomputedSignalStrategy`

Purpose:
- adapts the matrix of signals to the event engine.
- on each `BarEvent`, it checks the precomputed signal for that symbol and emits a `SignalEvent` only when it changes.

Key methods:
- `PrecomputedSignalStrategy.__init__(signals, symbols, engine)`
  - prepare lookup tables for bar/date/symbol mapping.
- `PrecomputedSignalStrategy.calculate(event)`
  - emit a signal only if the signal changes since the last emitted value.

## Signal logic

The main rule is a moving-average crossover:

```text
if fast MA crosses above slow MA => LONG
if fast MA crosses below slow MA => SHORT or FLAT (depending on config)
```

The signal persists until the next crossover, which makes position state continuous between event windows.

## Role in the backtest

```text
DataFeed.load_prices(...)
    ↓
VectorisedMACrossover.generate(prices)
    ↓
PrecomputedSignalStrategy
    ↓
SignalEvent
    ↓
LargeUniverseRiskManager.on_signal(event)
    ↓
OrderEvent / trade execution
```

## Summary

The `strategy` package is the intelligence layer: it converts price history into trade signals. In this project it mainly uses a vectorized MA crossover model, which is efficient enough for large-universe backtests.
