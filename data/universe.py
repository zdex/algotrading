"""
data/universe.py
----------------
Fetches index constituents for S&P 500, NASDAQ-100, and Dow Jones.
Uses a browser User-Agent to avoid Wikipedia's 403 block.
"""

import logging
import io
import urllib.request
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

# Mimics a real browser — prevents Wikipedia 403
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _read_html(url: str) -> list[pd.DataFrame]:
    """Drop-in for pd.read_html with a browser User-Agent."""
    req  = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read()
    return pd.read_html(io.StringIO(html.decode("utf-8")))


# ── Individual index fetchers ─────────────────────────────────

def get_sp500() -> list[str]:
    try:
        tables  = _read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        symbols = tables[0]["Symbol"].tolist()
        symbols = [s.replace(".", "-") for s in symbols]
        logger.info("S&P 500: %d symbols loaded.", len(symbols))
        return symbols
    except Exception as e:
        logger.error("Failed to fetch S&P 500: %s", e)
        return []


def get_nasdaq100() -> list[str]:
    try:
        tables = _read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for t in tables:
            if "Ticker" in t.columns:
                symbols = t["Ticker"].tolist()
                logger.info("NASDAQ-100: %d symbols loaded.", len(symbols))
                return symbols
        logger.warning("NASDAQ-100 table not found.")
        return []
    except Exception as e:
        logger.error("Failed to fetch NASDAQ-100: %s", e)
        return []


def get_dow30() -> list[str]:
    try:
        tables = _read_html("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average")
        for t in tables:
            if "Symbol" in t.columns:
                symbols = t["Symbol"].tolist()
                logger.info("Dow 30: %d symbols loaded.", len(symbols))
                return symbols
        logger.warning("Dow 30 table not found.")
        return []
    except Exception as e:
        logger.error("Failed to fetch Dow 30: %s", e)
        return []


def get_full_universe(
    include_sp500:  bool = True,
    include_nasdaq: bool = True,
    include_dow:    bool = True,
) -> list[str]:
    symbols: set[str] = set()
    if include_sp500:
        symbols.update(get_sp500())
    if include_nasdaq:
        symbols.update(get_nasdaq100())
    if include_dow:
        symbols.update(get_dow30())
    result = sorted(symbols)
    logger.info("Full universe: %d unique symbols.", len(result))
    return result


def get_sp500_sector_map() -> dict[str, str]:
    try:
        tables = _read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0][["Symbol", "GICS Sector"]].copy()
        df["Symbol"] = df["Symbol"].str.replace(".", "-")
        sector_map = df.set_index("Symbol")["GICS Sector"].to_dict()
        logger.info("Sector map: %d symbols mapped.", len(sector_map))
        return sector_map
    except Exception as e:
        logger.error("Failed to fetch sector map: %s", e)
        return {}