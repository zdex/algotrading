# Execution package flow

This package contains the broker and simulated trade execution layer used in backtests.

## Purpose

The `execution` package provides a paper trading execution adapter for historical backtests.

Main component:
- `SimulatedBroker` in `execution/adapters/simulated.py`

## High-level flow

```text
OrderEvent
    ↓
SimulatedBroker.on_order(event)
    ↓
queue / fill at next open or latest close
    ↓
FillEvent
    ↓
Portfolio.on_fill(event)
    ↓
position update + trade ledger update
```

## Main classes and functions

### `SimConfig`

File: `execution/adapters/simulated.py`

Purpose:
- holds broker execution settings:
  - `slippage_bps`
  - `commission_per_trade`
  - `fill_timing` (`"next_open"` or `"close"`)

### `SimulatedBroker`

File: `execution/adapters/simulated.py`

Key methods:
- `SimulatedBroker.__init__(engine, config)`
  - bind to the engine and store broker configuration.
- `SimulatedBroker.update_price(symbol, price)`
  - keep the latest market price for a symbol.
- `SimulatedBroker.on_bar(event: BarEvent)`
  - for next-open fills, execute orders queued for this symbol when the new bar arrives.
- `SimulatedBroker.on_order(event: OrderEvent)`
  - accept incoming order requests and route them to either queue or immediate fill.
- `SimulatedBroker.pending_orders()`
  - list active orders waiting for fill.
- `SimulatedBroker._fill(order, price, ts)`
  - generate a `FillEvent` from the order with slippage and commission.

Purpose:
- emulate a brokerage execution layer without needing a real broker.
- allow backtests to run with realistic fill timing and fees.

## Fill model

The default execution behavior is:

```text
next_open fill model
```

Meaning:
- an order created mid-bar waits until the next bar's open,
- then fills at that bar's open plus slippage,
- not at the close of the same bar.

This avoids same-bar look-ahead in the backtest simulation.

## How it interacts with the rest of the system

```text
LargeUniverseRiskManager
    ↓ creates OrderEvent
    ↓
SimulatedBroker.on_order()
    ↓
SimulatedBroker._fill()
    ↓
engine.put(FillEvent)
    ↓
Portfolio.on_fill()
    ↓
trade ledger + position updates
```

## Notes

- If the broker's `on_bar()` is not registered, the system falls back to a legacy close-fill mode with a warning.
- This compatibility mode prevents older scripts from breaking, but it introduces same-bar fill behaviour.

## Summary

The `execution` package is the simulation layer for trade handling. It converts risk-approved orders into realistic fills and feeds those fills back into the portfolio accounting system.
