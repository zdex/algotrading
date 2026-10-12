# Core package flow

This package contains the shared event-driven engine used by the backtester and the UI.

## Purpose

The `core` package provides:
- the event bus (`EventEngine`),
- event definitions (`BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`),
- portfolio state (`Portfolio`, `Position`, `Trade`),
- risk checks (`LargeUniverseRiskManager` in `core/risk_large.py`),
- and general execution of the model across historical and live workflows.

## High-level flow

```text
Market data / feed
    ↓
BarEvent
    ↓
EventEngine.start(data_feed)
    ↓
registered handlers
    ├─ strategy.on_bar / calculate(...)
    ├─ risk.on_signal(...)
    ├─ broker.on_order(...)
    ├─ portfolio.on_fill(...)
    └─ metrics/reporting
```

## Main classes and functions

### `EventEngine`

File: `core/engine.py`

Key methods:
- `EventEngine.__init__()`
  - create the event queue and handler registry.
- `EventEngine.register(event_type, handler)`
  - attach a callback to an event type.
- `EventEngine.put(event)`
  - enqueue a new event.
- `EventEngine._dispatch(event)`
  - deliver the event to all registered handlers.
- `EventEngine.start(data_feed)`
  - main engine loop: consume the feed and dispatch events until the stream ends.
- `EventEngine.stop()`
  - stop processing.

Purpose:
- central event bus for the backtest simulation.
- decouples pricing, strategy, risk, broker, and portfolio logic.

### `Portfolio`

File: `core/portfolio.py`

Key methods:
- `Portfolio.__post_init__()`
  - initialize cash.
- `Portfolio.on_fill(event)`
  - called on every `FillEvent` to update cash and open positions.
- `Portfolio.total_equity(prices)`
  - compute total net asset value.
- `Portfolio.total_realised_pnl()`
  - sum realised gains/losses from all closed trades.
- `Portfolio.summary(prices)`
  - give a concise portfolio snapshot.

Purpose:
- track open positions, cash, and realized/unrealized P&L.

### `Position`

File: `core/portfolio.py`

Key methods:
- `Position.update(fill)`
  - update the position after each fill.
  - if position is reduced/closed/reversed, create a `Trade` record.
- `Position.market_value(current_price)`
  - compute current mark-to-market value.
- `Position.unrealised_pnl(current_price)`
  - compute unrealized profit/loss.

Purpose:
- maintain per-symbol state and trade-level accounting.

### `Trade`

File: `core/portfolio.py`

Purpose:
- one closed round trip for a symbol.
- stores entry/exit time, quantity, price, gross P&L, commission, and net P&L.

### `LargeUniverseRiskManager`

File: `core/risk_large.py`

Key methods:
- `LargeUniverseRiskManager.__init__(...)`
  - bind the manager to the portfolio, engine, sector map, and price data.
- `LargeUniverseRiskManager.on_signal(event)`
  - main signal validation handler.
- `LargeUniverseRiskManager.update_price(symbol, price)`
  - updates latest market price.
- `LargeUniverseRiskManager.update_bar(event)`
  - records latest bar close for a symbol.
- `LargeUniverseRiskManager.update_equity(equity)`
  - updates peak equity for drawdown tracking.
- `LargeUniverseRiskManager._size_position(...)`
  - computes trade size under vol-targeting and caps.
- `LargeUniverseRiskManager._send(...)`
  - emits an `OrderEvent` if the signal passes all checks.

Purpose:
- enforce risk constraints before a trade is sent to the broker.

## Typical backtest sequence

```text
DataFeed => BarEvent => EventEngine
    ↓
PrecomputedSignalStrategy.calculate(event)
    ↓
SignalEvent
    ↓
LargeUniverseRiskManager.on_signal(event)
    ↓
OrderEvent
    ↓
SimulatedBroker.on_order(event)
    ↓
FillEvent
    ↓
Portfolio.on_fill(event)
    ↓
updated positions + trades + equity
```

## Summary

The `core` package ties the whole engine together. It is the shared execution layer that turns market bars into signals, risk decisions, orders, fills, and portfolio-level accounting.
