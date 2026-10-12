"""
data/feed.py
------------
Batch downloads OHLCV data via yfinance and caches to Parquet.

Design
------
- First run  : downloads from Yahoo Finance, saves to cache/
- Later runs : loads from Parquet (milliseconds vs minutes)
- Incremental: only re-fetches symbols that are missing or whose cached
               range does not cover the requested start/end. The requested
               range per symbol is recorded in cache/_coverage.json, so a
               symbol that simply has no older data (e.g. a recent IPO) is
               not re-downloaded on every run.

Usage
-----
    from data.feed import DataFeed
    feed = DataFeed(cache_dir="./data/cache")
    feed.download(symbols, start="2020-01-01", end="2024-01-01")
    prices = feed.load_prices(symbols, start="2021-01-01")   # dates × symbols
    bars   = feed.bar_generator(symbols, start="2021-01-01") # BarEvents in time order
"""

import json
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Generator, Optional

import pandas as pd
import yfinance as yf

from core.events import BarEvent

logger = logging.getLogger(__name__)

CACHE_DIR     = "./data/cache"
COVERAGE_FILE = "_coverage.json"
BATCH_SIZE    = 100      # yfinance sweet spot
REQUEST_DELAY = 1.0      # seconds between batches — avoids rate limiting


class DataFeed:

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    # ── Cache helpers ─────────────────────────────────────────

    def _cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol}.parquet")

    def _is_cached(self, symbol: str) -> bool:
        return os.path.exists(self._cache_path(symbol))

    # ── Coverage bookkeeping ──────────────────────────────────

    def _coverage_path(self) -> str:
        return os.path.join(self.cache_dir, COVERAGE_FILE)

    def _read_coverage(self) -> dict[str, dict]:
        try:
            with open(self._coverage_path()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_coverage(self, coverage: dict[str, dict]) -> None:
        with open(self._coverage_path(), "w") as f:
            json.dump(coverage, f, indent=1, sort_keys=True)

    def _covers(self, symbol: str, start: str, end: str, coverage: dict) -> bool:
        """True if the cache for `symbol` already covers [start, end)."""
        if not self._is_cached(symbol):
            return False
        rec = coverage.get(symbol)
        if rec:
            return rec["start"] <= start and rec["end"] >= end
        # No record (cache written by an older version): judge from the data itself
        df = self._load(symbol)
        if df is None or df.empty:
            return False
        first, last = df.index.min(), df.index.max()
        slack = timedelta(days=7)
        start_ok = first <= pd.Timestamp(start) + slack
        end_ok = last >= min(pd.Timestamp(end), pd.Timestamp.now().normalize()) - slack
        return bool(start_ok and end_ok)

    def coverage_report(self, symbols: Optional[list[str]] = None) -> pd.DataFrame:
        """Per-symbol cache status: first/last date, rows, requested range, file time."""
        if symbols is None:
            symbols = sorted(
                f[:-8] for f in os.listdir(self.cache_dir) if f.endswith(".parquet")
            )
        coverage = self._read_coverage()
        rows = []
        for symbol in symbols:
            path = self._cache_path(symbol)
            df = self._load(symbol) if os.path.exists(path) else None
            rec = coverage.get(symbol, {})
            rows.append({
                "symbol":          symbol,
                "cached":          df is not None,
                "first_date":      df.index.min() if df is not None and len(df) else pd.NaT,
                "last_date":       df.index.max() if df is not None and len(df) else pd.NaT,
                "rows":            len(df) if df is not None else 0,
                "requested_start": rec.get("start"),
                "requested_end":   rec.get("end"),
                "file_updated":    pd.Timestamp(os.path.getmtime(path), unit="s")
                                   if os.path.exists(path) else pd.NaT,
            })
        return pd.DataFrame(rows)

    def _save(self, symbol: str, df: pd.DataFrame) -> None:
        self._normalize_ohlcv(df).to_parquet(self._cache_path(symbol))

    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        FastParquet mishandles datetime64[s] indexes on round-trip (wrong 1970
        dates and duplicate labels). Use ns precision and drop duplicate dates.
        """
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        if getattr(df.index, "unit", None) != "ns":
            df.index = df.index.as_unit("ns")
        if df.index.duplicated().any():
            n = int(df.index.duplicated().sum())
            logger.warning("Dropping %d duplicate timestamps.", n)
            df = df[~df.index.duplicated(keep="last")]
        return df

    def _load(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self._cache_path(symbol)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_parquet(path)
            df = self._normalize_ohlcv(df)
            if len(df) and df.index.max().year < 1980:
                logger.warning(
                    "Cache for %s has invalid dates (Parquet corruption). "
                    "Re-download with force=True.",
                    symbol,
                )
                return None
            return df
        except Exception as e:
            logger.warning("Corrupt cache for %s: %s", symbol, e)
            return None

    # ── Download ──────────────────────────────────────────────

    def download(
        self,
        symbols:    list[str],
        start:      str,
        end:        str,
        interval:   str  = "1d",
        force:      bool = False,       # re-download even if cached
        batch_size: int  = BATCH_SIZE,
    ) -> dict[str, int]:
        """
        Downloads all symbols in batches, caches each to Parquet.

        Returns
        -------
        dict with counts: {"downloaded": N, "cached": N, "failed": N}
        """
        coverage = self._read_coverage()
        to_download = [
            s for s in symbols
            if force or not self._covers(s, start, end, coverage)
        ]
        cached = len(symbols) - len(to_download)
        logger.info(
            "%d symbols: %d cached, %d to download.",
            len(symbols), cached, len(to_download),
        )

        downloaded, failed = 0, 0
        batches = [
            to_download[i : i + batch_size]
            for i in range(0, len(to_download), batch_size)
        ]

        for idx, batch in enumerate(batches, 1):
            logger.info(
                "Batch %d/%d: downloading %d symbols...",
                idx, len(batches), len(batch),
            )
            try:
                raw = yf.download(
                    batch,
                    start    = start,
                    end      = end,
                    interval = interval,
                    auto_adjust = True,
                    progress    = False,
                    threads     = True,
                )

                for symbol in batch:
                    try:
                        df = self._extract_symbol(raw, symbol, len(batch))
                        if df is not None and len(df) > 0:
                            self._save(symbol, df)
                            coverage[symbol] = {"start": start, "end": end}
                            downloaded += 1
                        else:
                            logger.warning("No data for %s.", symbol)
                            failed += 1
                    except Exception as e:
                        logger.error("Failed to parse %s: %s", symbol, e)
                        failed += 1

            except Exception as e:
                logger.error("Batch %d failed: %s", idx, e)
                failed += len(batch)

            # Rate limit courtesy pause between batches
            if idx < len(batches):
                time.sleep(REQUEST_DELAY)

        self._write_coverage(coverage)
        logger.info(
            "Download complete. downloaded=%d cached=%d failed=%d",
            downloaded, cached, failed,
        )
        return {"downloaded": downloaded, "cached": cached, "failed": failed}

    def _extract_symbol(
        self,
        raw: pd.DataFrame,
        symbol: str,
        batch_len: int,
    ) -> Optional[pd.DataFrame]:
        """Extract single-symbol OHLCV from a possibly MultiIndex DataFrame."""
        if batch_len == 1:
            df = raw.copy()
        else:
            if symbol not in raw.columns.get_level_values(1):
                return None
            df = raw.xs(symbol, axis=1, level=1)

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index.name = "timestamp"
        df = df.dropna(subset=["close"])
        return self._normalize_ohlcv(df)

    # ── Load ──────────────────────────────────────────────────

    @staticmethod
    def _slice(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        """Rows in [start, end) — end is exclusive, matching yfinance."""
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index < pd.Timestamp(end)]
        return df

    def load_prices(
        self,
        symbols: list[str],
        column:  str = "close",
        start:   Optional[str] = None,
        end:     Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Returns a wide DataFrame: index=dates, columns=symbols.
        Missing symbols are silently skipped.
        Used by vectorised strategy and correlation checks.
        """
        frames = {}
        for symbol in symbols:
            df = self._load(symbol)
            if df is not None and column in df.columns:
                frames[symbol] = self._slice(df, start, end)[column]

        if not frames:
            return pd.DataFrame()

        result = pd.DataFrame(frames)
        result.index = pd.to_datetime(result.index)
        result.sort_index(inplace=True)
        logger.info(
            "Loaded price matrix: %d dates × %d symbols.",
            len(result), len(result.columns),
        )
        return result

    def load_ohlcv(
        self,
        symbol: str,
        start:  Optional[str] = None,
        end:    Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Load OHLCV for a single symbol (optionally sliced to [start, end))."""
        df = self._load(symbol)
        if df is None:
            return None
        return self._slice(df, start, end)

    # ── Bar generator ─────────────────────────────────────────

    def bar_generator(
        self,
        symbols:  list[str],
        interval: str = "1d",
        start:    Optional[str] = None,
        end:      Optional[str] = None,
    ) -> Generator[BarEvent, None, None]:
        """
        Yields BarEvents in strict chronological order across all symbols,
        restricted to [start, end) when given.
        """
        frames = []
        for symbol in symbols:
            df = self._load(symbol)
            if df is None:
                continue
            df = self._slice(df, start, end)
            if df.empty:
                continue
            df = df.reindex(columns=["open", "high", "low", "close", "volume"])
            df = df.dropna(subset=["close"])
            for col in ("open", "high", "low"):
                df[col] = df[col].fillna(df["close"])   # never fill an order at a 0 price
            df["volume"] = df["volume"].fillna(0.0)
            df = df.assign(symbol=symbol)
            frames.append(df)

        if not frames:
            logger.info("Bar generator ready: 0 total bars.")
            return

        # Sort by timestamp, then symbol (deterministic ordering)
        all_bars = pd.concat(frames)
        all_bars.index.name = "timestamp"
        all_bars = all_bars.reset_index().sort_values(["timestamp", "symbol"], kind="mergesort")
        logger.info("Bar generator ready: %d total bars.", len(all_bars))

        for row in all_bars.itertuples(index=False):
            yield BarEvent(
                timestamp = row.timestamp.to_pydatetime(),
                symbol    = row.symbol,
                open      = float(row.open),
                high      = float(row.high),
                low       = float(row.low),
                close     = float(row.close),
                volume    = float(row.volume),
                interval  = interval,
            )
