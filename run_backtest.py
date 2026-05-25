"""
run_backtest.py
---------------
End-to-end backtest wiring everything together.

Demonstrates the full event flow:
  BarFeed → Engine → Strategy → RiskManager → SimBroker → Portfolio

Run with:
    pip install yfinance pandas
    python run_backtest.py
"""

import logging
import yfinance as yf
import pandas as pd

from core.engine      import EventEngine
from core.events      import BarEvent, EventType
from core.portfolio   import Portfolio
from core.risk        import RiskManager, RiskConfig
from execution.adapters.simulated import SimulatedBroker, SimConfig
from strategy.examples.ma_crossover import MACrossoverStrategy
from backtester.metrics import summary_report

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger("backtest")


# ── Config ────────────────────────────────────────────────────

SYMBOLS      = ["AAPL", "MSFT", "NVDA"]
START_DATE   = "2022-01-01"
END_DATE     = "2024-01-01"
INITIAL_CASH = 100_000.0


# ── Data feed generator ───────────────────────────────────────

def historical_bar_feed(symbols: list, start: str, end: str):
    """
    Downloads daily OHLCV data via yfinance and yields BarEvents
    in chronological order across all symbols.
    """
    logger.info("Downloading data for %s …", symbols)
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)

    # yfinance returns MultiIndex columns when multiple tickers
    bars = []
    for symbol in symbols:
        try:
            df = raw.xs(symbol, axis=1, level=1) if len(symbols) > 1 else raw
            df = df.dropna()
            for ts, row in df.iterrows():
                bars.append(
                    BarEvent(
                        timestamp = ts.to_pydatetime(),
                        symbol    = symbol,
                        open      = float(row["Open"]),
                        high      = float(row["High"]),
                        low       = float(row["Low"]),
                        close     = float(row["Close"]),
                        volume    = float(row["Volume"]),
                        interval  = "1d",
                    )
                )
        except Exception as e:
            logger.warning("Skipping %s: %s", symbol, e)

    bars.sort(key=lambda b: (b.timestamp, b.symbol))
    logger.info("Loaded %d bars across %d symbols.", len(bars), len(symbols))
    return bars


# ── Wiring ────────────────────────────────────────────────────

def run():
    # 1. Engine
    engine = EventEngine()

    # 2. Components
    portfolio  = Portfolio(initial_cash=INITIAL_CASH)
    broker     = SimulatedBroker(engine, SimConfig(slippage_bps=3, commission_per_trade=1.0))
    risk       = RiskManager(
        portfolio,
        engine,
        RiskConfig(
            max_position_pct   = 0.15,
            max_open_positions = 5,
            max_drawdown_pct   = 0.25,
            default_order_pct  = 0.08,
        ),
    )
    strategy   = MACrossoverStrategy(
        symbols     = SYMBOLS,
        fast_period = 10,
        slow_period = 30,
        allow_short = False,
        engine      = engine,
    )

    # 3. Wire event handlers
    engine.register(EventType.BAR,    strategy.on_bar)
    engine.register(EventType.BAR,    _price_updater(broker, risk))   # keep prices fresh
    engine.register(EventType.SIGNAL, risk.on_signal)
    engine.register(EventType.ORDER,  broker.on_order)
    engine.register(EventType.FILL,   portfolio.on_fill)

    # 4. Track equity curve
    equity_curve: list[float] = [INITIAL_CASH]
    last_prices: dict[str, float] = {}

    def _track_equity(event: BarEvent):
        last_prices[event.symbol] = event.close
        equity_curve.append(portfolio.total_equity(last_prices))

    engine.register(EventType.BAR, _track_equity)

    # 5. Run
    bars = historical_bar_feed(SYMBOLS, START_DATE, END_DATE)
    engine.start(iter(bars))

    # 6. Results
    fills = portfolio.fill_history
    pnl_per_trade = []
    for i in range(0, len(fills) - 1, 2):
        entry, exit_ = fills[i], fills[i + 1]
        pnl_per_trade.append(exit_.fill_price - entry.fill_price)

    print("\n" + "=" * 50)
    print("  BACKTEST RESULTS")
    print("=" * 50)
    report = summary_report(equity_curve, pnl_per_trade)
    for k, v in report.items():
        print(f"  {k:<22} {v}")
    print("=" * 50)
    print(portfolio.summary(last_prices))


# ── Helper ────────────────────────────────────────────────────

def _price_updater(broker, risk):
    """Returns a handler that updates broker & risk prices on every bar."""
    def handler(event: BarEvent):
        broker.update_price(event.symbol, event.close)
        risk.update_price(event.symbol, event.close)
    return handler


if __name__ == "__main__":
    run()
