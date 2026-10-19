"""Price-action agent.

Stage 1 is a tool: download OHLCV bars for a symbol and timeframe.
Stage 2 is code: trend, swings, support and resistance, breakouts, gaps, and
volume are numbers and flags. The LLM only reads that summary.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DAILY = "1d"
FIVE_MINUTE = "5m"
SWING_SPAN = 2
BREAKOUT_LOOKBACK = 20
VOLUME_LOOKBACK = 20
GAP_THRESHOLD = 0.005


@dataclass
class SwingPoint:
    date: str
    price: float
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PriceActionSummary:
    symbol: str
    timeframe: str
    bars: int = 0
    first_date: str = ""
    last_date: str = ""
    last_close: float | None = None
    trend: str = "unknown"
    swing_highs: list[SwingPoint] = field(default_factory=list)
    swing_lows: list[SwingPoint] = field(default_factory=list)
    support: float | None = None
    resistance: float | None = None
    distance_to_support_pct: float | None = None
    distance_to_resistance_pct: float | None = None
    breakout: str = "none"
    gap_pct: float | None = None
    volume_vs_average: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["swing_highs"] = [point.to_dict() for point in self.swing_highs]
        payload["swing_lows"] = [point.to_dict() for point in self.swing_lows]
        return payload

    def brief(self) -> str:
        if self.error:
            return f"Price action for {self.symbol}: {self.error}"
        highs = ", ".join(f"{point.date} {point.price:.2f}" for point in self.swing_highs[-3:]) or "none"
        lows = ", ".join(f"{point.date} {point.price:.2f}" for point in self.swing_lows[-3:]) or "none"
        support = _num(self.support)
        resistance = _num(self.resistance)
        return "\n".join([
            f"Price action ({self.timeframe}, {self.bars} bars, {self.first_date} to {self.last_date}):",
            f"- last close { _num(self.last_close) }",
            f"- trend: {self.trend}",
            f"- recent swing highs: {highs}",
            f"- recent swing lows: {lows}",
            f"- support {support}; close is {_pct(self.distance_to_support_pct)} versus that level",
            f"- resistance {resistance}; close is {_pct(self.distance_to_resistance_pct)} versus that level",
            f"- breakout: {self.breakout}",
            f"- latest gap: {_pct(self.gap_pct)}",
            f"- volume vs 20-bar average: {_num(self.volume_vs_average)}x",
        ])


class PriceActionAgent:
    """Fetch bars, then compute price-action features. Does not call a model."""

    def collect(self, symbol: str, name: str) -> tuple[PriceActionSummary, str | None]:
        summary = self.analyze(symbol)
        return summary, summary.error

    def analyze(
        self,
        symbol: str,
        timeframe: str = DAILY,
        lookback_days: int | None = None,
    ) -> PriceActionSummary:
        symbol = symbol.strip().upper()
        try:
            bars = fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        except Exception as exc:
            logger.warning("Bar fetch failed for %s: %s", symbol, exc)
            return PriceActionSummary(symbol=symbol, timeframe=timeframe, error=f"Bar fetch failed: {exc}")
        if bars.empty:
            return PriceActionSummary(symbol=symbol, timeframe=timeframe, error="No bars returned.")
        return summarize(symbol, timeframe, bars)


def fetch_bars(
    symbol: str,
    timeframe: str = DAILY,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    """Download OHLCV. Daily uses about a year. Five-minute uses the recent window Yahoo allows."""
    if timeframe not in {DAILY, FIVE_MINUTE}:
        raise ValueError(f"Unsupported timeframe {timeframe}. Use {DAILY} or {FIVE_MINUTE}.")
    if lookback_days is None:
        lookback_days = 60 if timeframe == FIVE_MINUTE else 420
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    raw = yf.download(
        symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        interval=timeframe,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    return _normalize_bars(raw, symbol)


def summarize(symbol: str, timeframe: str, bars: pd.DataFrame) -> PriceActionSummary:
    frame = bars.dropna(subset=["close"]).copy()
    if len(frame) < SWING_SPAN * 2 + 3:
        return PriceActionSummary(
            symbol=symbol,
            timeframe=timeframe,
            bars=len(frame),
            error="Not enough bars to mark swings.",
        )
    highs, lows = _swings(frame)
    close = float(frame["close"].iloc[-1])
    support = _nearest_below(lows, close)
    resistance = _nearest_above(highs, close)
    trend = _trend(highs, lows)
    breakout = _breakout(frame)
    gap = _gap(frame)
    volume_ratio = _volume_ratio(frame)
    return PriceActionSummary(
        symbol=symbol,
        timeframe=timeframe,
        bars=len(frame),
        first_date=_stamp(frame.index[0]),
        last_date=_stamp(frame.index[-1]),
        last_close=round(close, 4),
        trend=trend,
        swing_highs=highs[-4:],
        swing_lows=lows[-4:],
        support=None if support is None else round(support, 4),
        resistance=None if resistance is None else round(resistance, 4),
        distance_to_support_pct=_distance(close, support),
        distance_to_resistance_pct=_distance(close, resistance),
        breakout=breakout,
        gap_pct=None if gap is None else round(gap * 100, 2),
        volume_vs_average=None if volume_ratio is None else round(volume_ratio, 2),
    )


def _normalize_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        level = 1 if symbol in frame.columns.get_level_values(1) else 0
        if symbol in frame.columns.get_level_values(level):
            frame = frame.xs(symbol, axis=1, level=level)
        else:
            frame.columns = frame.columns.droplevel(-1)
    rename = {name: str(name).strip().lower() for name in frame.columns}
    frame = frame.rename(columns=rename)
    needed = ["open", "high", "low", "close", "volume"]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        return pd.DataFrame(columns=needed)
    frame = frame[needed].dropna(subset=["close"])
    frame.index = pd.to_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def _swings(frame: pd.DataFrame, span: int = SWING_SPAN) -> tuple[list[SwingPoint], list[SwingPoint]]:
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    index = frame.index
    for i in range(span, len(frame) - span):
        window_high = high[i - span:i + span + 1]
        window_low = low[i - span:i + span + 1]
        if high[i] == window_high.max() and (window_high == high[i]).sum() == 1:
            highs.append(SwingPoint(_stamp(index[i]), round(float(high[i]), 4), "high"))
        if low[i] == window_low.min() and (window_low == low[i]).sum() == 1:
            lows.append(SwingPoint(_stamp(index[i]), round(float(low[i]), 4), "low"))
    return highs, lows


def _trend(highs: list[SwingPoint], lows: list[SwingPoint]) -> str:
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    higher_highs = highs[-1].price > highs[-2].price
    higher_lows = lows[-1].price > lows[-2].price
    lower_highs = highs[-1].price < highs[-2].price
    lower_lows = lows[-1].price < lows[-2].price
    if higher_highs and higher_lows:
        return "uptrend"
    if lower_highs and lower_lows:
        return "downtrend"
    return "range"


def _nearest_below(lows: list[SwingPoint], close: float) -> float | None:
    below = [point.price for point in lows if point.price <= close]
    return below[-1] if below else None


def _nearest_above(highs: list[SwingPoint], close: float) -> float | None:
    above = [point.price for point in highs if point.price >= close]
    return above[-1] if above else None


def _distance(close: float, level: float | None) -> float | None:
    if level is None or level == 0:
        return None
    return round((close / level - 1) * 100, 2)


def _breakout(frame: pd.DataFrame) -> str:
    if len(frame) <= BREAKOUT_LOOKBACK:
        return "none"
    prior = frame.iloc[-(BREAKOUT_LOOKBACK + 1):-1]
    close = float(frame["close"].iloc[-1])
    if close > float(prior["high"].max()):
        return "above_prior_range"
    if close < float(prior["low"].min()):
        return "below_prior_range"
    return "none"


def _gap(frame: pd.DataFrame) -> float | None:
    if len(frame) < 2:
        return None
    previous_close = float(frame["close"].iloc[-2])
    opened = float(frame["open"].iloc[-1])
    if previous_close == 0:
        return None
    change = opened / previous_close - 1
    if abs(change) < GAP_THRESHOLD:
        return 0.0
    return change


def _volume_ratio(frame: pd.DataFrame) -> float | None:
    if len(frame) < VOLUME_LOOKBACK + 1:
        return None
    baseline = float(frame["volume"].iloc[-(VOLUME_LOOKBACK + 1):-1].mean())
    if baseline == 0:
        return None
    return float(frame["volume"].iloc[-1]) / baseline


def _stamp(value) -> str:
    ts = pd.Timestamp(value)
    if ts.hour == 0 and ts.minute == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"
