"""
data/feed.py
------------
Batch downloads OHLCV data via yfinance and caches to Parquet.

Design
------
- First run  : downloads from Yahoo Finance, saves to cache/
- Later runs : loads from Parquet (milliseconds vs minutes)
- Incremental: only re-fetches missing or stale symbols

Usage
-----
    from data.feed import DataFeed
    feed = DataFeed(cache_dir="./data/cache")
    feed.download(symbols, start="2020-01-01", end="2024-01-01")
    prices = feed.load_prices(symbols)   # DataFrame: dates × symbols
    bars   = feed.bar_generator(symbols) # yields BarEvents chronologically
"""

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
        to_download = [
            s for s in symbols
            if force or not self._is_cached(s)
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

    def load_prices(
        self,
        symbols: list[str],
        column:  str = "close",
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
                frames[symbol] = df[column]

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

    def load_ohlcv(self, symbol: str) -> Optional[pd.DataFrame]:
        """Load full OHLCV for a single symbol."""
        return self._load(symbol)

    # ── Bar generator ─────────────────────────────────────────

    def bar_generator(
        self,
        symbols:  list[str],
        interval: str = "1d",
    ) -> Generator[BarEvent, None, None]:
        """
        Yields BarEvents in strict chronological order across all symbols.
        Memory-efficient: streams from Parquet row by row.
        """
        all_bars: list[tuple[datetime, str, dict]] = []

        for symbol in symbols:
            df = self._load(symbol)
            if df is None:
                continue
            for ts, row in df.iterrows():
                all_bars.append((
                    pd.Timestamp(ts).to_pydatetime(),
                    symbol,
                    row.to_dict(),
                ))

        # Sort by timestamp, then symbol (deterministic ordering)
        all_bars.sort(key=lambda x: (x[0], x[1]))
        logger.info("Bar generator ready: %d total bars.", len(all_bars))

        for ts, symbol, row in all_bars:
            yield BarEvent(
                timestamp = ts,
                symbol    = symbol,
                open      = float(row.get("open",  0)),
                high      = float(row.get("high",  0)),
                low       = float(row.get("low",   0)),
                close     = float(row.get("close", 0)),
                volume    = float(row.get("volume",0)),
                interval  = interval,
            )
