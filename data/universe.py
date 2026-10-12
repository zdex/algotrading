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

def get_nasdaq100_sector_map() -> dict[str, str]:
    """GICS sectors for NASDAQ-100 names (many are not in the S&P 500 table)."""
    try:
        tables = _read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for t in tables:
            if "Ticker" in t.columns:
                col = next((c for c in t.columns if "Sector" in str(c)), None)
                if col is None:
                    return {}
                df = t[["Ticker", col]].copy()
                df["Ticker"] = df["Ticker"].astype(str).str.replace(".", "-")
                return df.set_index("Ticker")[col].to_dict()
        return {}
    except Exception as e:
        logger.error("Failed to fetch NASDAQ-100 sectors: %s", e)
        return {}


def get_sector_map() -> dict[str, str]:
    """S&P 500 sectors, filled in with NASDAQ-100 sectors for names outside the S&P."""
    sectors = get_nasdaq100_sector_map()
    sectors.update(get_sp500_sector_map())
    return sectors


# ── Dated universe snapshot (cache) ───────────────────────────
#
# Wikipedia lists are TODAY's constituents. Backtesting them over past
# years has survivorship bias: companies that left the index are missing.
# Saving a dated snapshot at least makes runs reproducible and lets the
# UI show which list a backtest used.

UNIVERSE_FILE = "_universe.csv"


def build_universe_table(
    include_sp500:  bool = True,
    include_nasdaq: bool = True,
    include_dow:    bool = True,
) -> pd.DataFrame:
    """Fetch constituents + sectors into one table with index membership flags."""
    sp   = set(get_sp500())      if include_sp500  else set()
    nq   = set(get_nasdaq100())  if include_nasdaq else set()
    dow  = set(get_dow30())      if include_dow    else set()
    sectors = get_sector_map()
    symbols = sorted(sp | nq | dow)
    return pd.DataFrame({
        "symbol":     symbols,
        "sector":     [sectors.get(s, "Unknown") for s in symbols],
        "sp500":      [s in sp for s in symbols],
        "nasdaq100":  [s in nq for s in symbols],
        "dow30":      [s in dow for s in symbols],
        "fetched_at": pd.Timestamp.now().normalize(),
    })


def load_universe(
    cache_dir:    str  = "./data/cache",
    max_age_days: int  = 7,
    refresh:      bool = False,
) -> pd.DataFrame:
    """
    Return the cached universe table, re-fetching from Wikipedia when it is
    missing, older than `max_age_days`, or `refresh=True`. Falls back to the
    stale cache if the fetch fails (e.g. offline).
    """
    import os
    path = os.path.join(cache_dir, UNIVERSE_FILE)
    cached = None
    if os.path.exists(path):
        cached = pd.read_csv(path, parse_dates=["fetched_at"])

    fresh_enough = (
        cached is not None and not cached.empty
        and (pd.Timestamp.now() - cached["fetched_at"].max()).days <= max_age_days
    )
    if fresh_enough and not refresh:
        return cached

    table = build_universe_table()
    if table.empty:
        if cached is not None:
            logger.warning("Universe fetch failed — using cached list from %s.",
                           cached["fetched_at"].max().date())
            return cached
        return table

    os.makedirs(cache_dir, exist_ok=True)
    table.to_csv(path, index=False)
    stamp = table["fetched_at"].iloc[0].strftime("%Y%m%d")
    table.to_csv(os.path.join(cache_dir, f"_universe_{stamp}.csv"), index=False)
    return table


def select_symbols(
    table: pd.DataFrame,
    include_sp500:  bool = True,
    include_nasdaq: bool = True,
    include_dow:    bool = True,
) -> list[str]:
    mask = pd.Series(False, index=table.index)
    if include_sp500:
        mask |= table["sp500"].astype(bool)
    if include_nasdaq:
        mask |= table["nasdaq100"].astype(bool)
    if include_dow:
        mask |= table["dow30"].astype(bool)
    return sorted(table.loc[mask, "symbol"].tolist())
