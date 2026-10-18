"""
data/universe.py
----------------
Fetches index constituents for S&P 500, NASDAQ-100, and Dow Jones.
Uses a browser User-Agent to avoid Wikipedia's 403 block.
"""

import html
import json
import logging
import io
import os
import re
import subprocess
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


def _fetch_html(url: str) -> bytes:
    """Download a public page. Falls back to the OS trust store when Python's CA bundle fails."""
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        reason = str(getattr(exc, "reason", exc))
        if "SSL" not in reason.upper() and "CERTIFICATE" not in reason.upper():
            raise
        logger.warning("Python TLS verify failed (%s). Retrying with the system certificate store.", reason)
        completed = subprocess.run(
            ["curl.exe", "-fsSL", "--max-time", "30", "-A", _HEADERS["User-Agent"], url],
            check=True,
            capture_output=True,
        )
        return completed.stdout


def _read_html(url: str) -> list[pd.DataFrame]:
    """Drop-in for pd.read_html with a browser User-Agent."""
    html = _fetch_html(url)
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
        tables = _read_html(_NASDAQ100_COMPANIES_URL)
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
        symbols = [symbol for symbol, _name in get_dow30_companies()]
        logger.info("Dow 30: %d symbols loaded.", len(symbols))
        return symbols
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
        tables = _read_html(_NASDAQ100_COMPANIES_URL)
        for t in tables:
            if "Ticker" in t.columns:
                col = next((c for c in t.columns if "Industry" in str(c) and "Sub" not in str(c)), None)
                if col is None:
                    col = next((c for c in t.columns if "Sector" in str(c) and "Sub" not in str(c)), None)
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


# ── Company directory (name + ticker + index membership) ──────
#
# The trading universe above is symbols only. The company picker needs the
# security name next to the ticker, with one row when a name sits in more
# than one index.

COMPANIES_FILE = "_companies.csv"
_NASDAQ100_COMPANIES_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
_DOW_COMPONENTS_API = (
    "https://en.wikipedia.org/w/api.php?action=parse"
    "&page=Template:Dow_Jones_Industrial_Average_companies"
    "&prop=wikitext&format=json"
)
_NAME_DROP = {
    "incorporated", "inc", "corp", "corporation", "company", "companies",
    "plc", "ltd", "co", "group", "holdings", "holding", "the", "class",
}
_DOW_NAME_ALIASES = {
    "ibm": "international business machines",
}
_INDEX_LABELS = (
    ("sp500", "S&P 500"),
    ("nasdaq100", "NASDAQ-100"),
    ("dow30", "Dow 30"),
)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            " ".join(str(part) for part in col if str(part) not in {"", "nan"}).strip()
            for col in out.columns
        ]
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _find_col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        hit = lookup.get(name.lower())
        if hit is not None:
            return hit
    for name in names:
        needle = name.lower()
        for key, col in lookup.items():
            if needle in key:
                return col
    return None


def _clean_symbol(value) -> str:
    text = str(value).strip().upper()
    text = re.sub(r"\[.*?\]", "", text)
    text = text.replace(".", "-")
    text = re.sub(r"[^A-Z0-9\-]", "", text.split()[0] if text else "")
    return text


def _clean_name(value) -> str:
    text = re.sub(r"\[.*?\]", "", str(value))
    return " ".join(text.split())


def _pairs_from_table(df: pd.DataFrame, symbol_names: tuple[str, ...], name_names: tuple[str, ...]) -> list[tuple[str, str]]:
    df = _flatten_columns(df)
    sym_col = _find_col(df, *symbol_names)
    name_col = _find_col(df, *name_names)
    if sym_col is None or name_col is None:
        return []
    pairs: list[tuple[str, str]] = []
    for symbol, name in zip(df[sym_col], df[name_col]):
        ticker = _clean_symbol(symbol)
        company = _clean_name(name)
        if not ticker or ticker == "NAN" or not company or company.lower() == "nan":
            continue
        pairs.append((ticker, company))
    return pairs


def get_sp500_companies() -> list[tuple[str, str]]:
    try:
        tables = _read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        pairs = _pairs_from_table(tables[0], ("Symbol", "Ticker"), ("Security", "Company", "Name"))
        logger.info("S&P 500 companies: %d names loaded.", len(pairs))
        return pairs
    except Exception as e:
        logger.error("Failed to fetch S&P 500 companies: %s", e)
        return []


def _closest(candidates: list[list[tuple[str, str]]], target: int) -> list[tuple[str, str]]:
    return min(candidates, key=lambda pairs: (abs(len(pairs) - target), -len(pairs)))


def get_nasdaq100_companies() -> list[tuple[str, str]]:
    try:
        tables = _read_html(_NASDAQ100_COMPANIES_URL)
        candidates = []
        for table in tables:
            pairs = _pairs_from_table(table, ("Ticker", "Symbol"), ("Company", "Security", "Name"))
            if 90 <= len(pairs) <= 110:
                candidates.append(pairs)
        if not candidates:
            logger.warning("NASDAQ-100 company table not found.")
            return []
        pairs = _closest(candidates, 101)
        logger.info("NASDAQ-100 companies: %d names loaded.", len(pairs))
        return pairs
    except Exception as e:
        logger.error("Failed to fetch NASDAQ-100 companies: %s", e)
        return []


def _norm_name(name: str) -> str:
    text = html.unescape(str(name))
    text = re.sub(r"\s*\([^)]*\)", " ", text)
    text = text.lower().replace("&", " and ").replace("'", "")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    parts = [part for part in text.split() if part not in _NAME_DROP]
    return " ".join(parts)


def _dow_component_labels() -> list[str]:
    """Display names from the Dow components navbox. That page no longer has a ticker table."""
    payload = json.loads(_fetch_html(_DOW_COMPONENTS_API).decode("utf-8"))
    wikitext = payload["parse"]["wikitext"]["*"]
    wikitext = re.sub(r"<noinclude>.*?</noinclude>", "", wikitext, flags=re.S)
    labels = []
    for match in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]", wikitext):
        title = html.unescape(match.group(1)).strip()
        label = html.unescape((match.group(2) or title)).strip()
        if not label or title.lower() == "dow jones industrial average":
            continue
        labels.append(label)
    return labels


def _prefer_match(candidates: list[tuple[str, str]], key: str) -> tuple[str, str]:
    class_a = [item for item in candidates if "class a" in item[1].lower()]
    if len(class_a) == 1:
        return class_a[0]
    return min(candidates, key=lambda item: (abs(len(_norm_name(item[1])) - len(key)), item[0]))


def _match_dow_name(label: str, companies: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
    key = _DOW_NAME_ALIASES.get(_norm_name(label), _norm_name(label))
    if not key:
        return None
    exact = []
    partial = []
    for symbol, name in companies:
        other = _DOW_NAME_ALIASES.get(_norm_name(name), _norm_name(name))
        if other == key:
            exact.append((symbol, name))
        elif len(key) >= 3 and (key in other or other in key):
            partial.append((symbol, name))
    pool = exact or partial
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    logger.info("Dow name %s matched %s.", label, [item[0] for item in pool])
    return _prefer_match(pool, key)


def get_dow30_companies(
    sp500: Optional[list[tuple[str, str]]] = None,
) -> list[tuple[str, str]]:
    """Dow names joined to S&P 500 tickers. Every current Dow component is also in the S&P 500."""
    try:
        labels = _dow_component_labels()
        universe = sp500 if sp500 is not None else get_sp500_companies()
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label in labels:
            match = _match_dow_name(label, universe)
            if match is None:
                logger.warning("No S&P 500 ticker for Dow component %s.", label)
                continue
            if match[0] in seen:
                continue
            seen.add(match[0])
            pairs.append(match)
        logger.info("Dow 30 companies: %d names loaded.", len(pairs))
        return pairs
    except Exception as e:
        logger.error("Failed to fetch Dow 30 companies: %s", e)
        return []


def _index_label(row: pd.Series) -> str:
    labels = [label for flag, label in _INDEX_LABELS if bool(row[flag])]
    return ", ".join(labels)


def build_company_directory(
    include_sp500:  bool = True,
    include_nasdaq: bool = True,
    include_dow:    bool = True,
) -> pd.DataFrame:
    """One row per company: ticker, name, and which of the three indexes it belongs to."""
    rows: dict[str, dict] = {}

    def add(pairs: list[tuple[str, str]], flag: str) -> None:
        for symbol, name in pairs:
            row = rows.setdefault(symbol, {
                "symbol": symbol,
                "name": name,
                "sp500": False,
                "nasdaq100": False,
                "dow30": False,
            })
            if name and (not row["name"] or row["name"] == symbol):
                row["name"] = name
            row[flag] = True

    sp500 = get_sp500_companies() if include_sp500 or include_dow else []
    if include_sp500:
        add(sp500, "sp500")
    if include_nasdaq:
        add(get_nasdaq100_companies(), "nasdaq100")
    if include_dow:
        add(get_dow30_companies(sp500), "dow30")

    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "sp500", "nasdaq100", "dow30", "indexes", "fetched_at"])

    table = pd.DataFrame(rows.values())
    table["indexes"] = table.apply(_index_label, axis=1)
    table["fetched_at"] = pd.Timestamp.now().floor("s")
    return table.sort_values(["name", "symbol"]).reset_index(drop=True)


def load_company_directory(
    cache_dir:    str  = "./data/cache",
    max_age_days: int  = 7,
    refresh:      bool = False,
) -> pd.DataFrame:
    """
    Cached company directory for the picker. Re-fetches Wikipedia when the file
    is missing, older than `max_age_days`, or `refresh=True`. Uses the stale
    file if the fetch fails.
    """
    path = os.path.join(cache_dir, COMPANIES_FILE)
    cached = None
    if os.path.exists(path):
        cached = pd.read_csv(path, parse_dates=["fetched_at"])
        for col in ("sp500", "nasdaq100", "dow30"):
            if col in cached.columns:
                cached[col] = cached[col].astype(bool)

    fresh_enough = (
        cached is not None and not cached.empty
        and (pd.Timestamp.now() - cached["fetched_at"].max()).days <= max_age_days
    )
    if fresh_enough and not refresh:
        return cached

    table = build_company_directory()
    if table.empty:
        if cached is not None:
            logger.warning("Company directory fetch failed — using cached list from %s.",
                           cached["fetched_at"].max().date())
            return cached
        return table

    os.makedirs(cache_dir, exist_ok=True)
    table.to_csv(path, index=False)
    return table
