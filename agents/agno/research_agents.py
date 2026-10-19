"""Research agents used by the company analysis orchestrator.

FilingsAgent reads SEC EDGAR for yearly and quarterly reports.
NewsAgent reads a public news RSS search.
PriceActionAgent downloads OHLCV bars and computes price structure.
SocialAgent reads recent X posts when X_BEARER_TOKEN is set, then scores
sentiment with the existing keyword scanner. None of these agents call an LLM.
"""
from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from agents.agno.analysis_agents import SentimentAnalysis
from agents.agno.config import ROOT, env_secret
from agents.agno.http_util import get_bytes
from agents.agno.price_action import PriceActionAgent, PriceActionSummary, SwingPoint

logger = logging.getLogger(__name__)

RESEARCH_DIR = ROOT / "data" / "agents" / "research"
CACHE_HOURS = 24
NEWS_LIMIT = 12
SOCIAL_LIMIT = 10
FILING_LIMIT = 40
FILING_FORMS = {"10-K", "10-Q", "20-F", "6-K"}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
NEWS_RSS = "https://news.google.com/rss/search"
X_SEARCH = "https://api.twitter.com/2/tweets/search/recent"
SEC_HEADERS = {
    "User-Agent": "algotrading research bot admin@localhost",
    "Accept": "application/json",
}
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

_ticker_map: dict[str, dict[str, str]] | None = None


@dataclass
class FilingRecord:
    symbol: str
    form: str
    period_end: str
    filed_at: str
    source: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsItem:
    symbol: str
    title: str
    source: str
    published_at: str
    url: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SocialPost:
    symbol: str
    author: str
    text: str
    posted_at: str
    url: str
    sentiment: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompanyEvidence:
    symbol: str
    name: str
    filings: list[FilingRecord] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    social: list[SocialPost] = field(default_factory=list)
    price_action: PriceActionSummary | None = None
    errors: list[str] = field(default_factory=list)
    fetched_at: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["filings"] = [item.to_dict() for item in self.filings]
        payload["news"] = [item.to_dict() for item in self.news]
        payload["social"] = [item.to_dict() for item in self.social]
        payload["price_action"] = self.price_action.to_dict() if self.price_action else None
        return payload


def _cache_path(symbol: str) -> Path:
    safe = re.sub(r"[^A-Z0-9\-]", "", symbol.upper()) or "UNKNOWN"
    return RESEARCH_DIR / safe / "evidence.json"


def load_cached_evidence(symbol: str, name: str, max_age_hours: int = CACHE_HOURS) -> CompanyEvidence | None:
    path = _cache_path(symbol)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(raw["fetched_at"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    if datetime.now() - fetched > timedelta(hours=max_age_hours):
        return None
    evidence = _evidence_from_dict(raw, name)
    if evidence.price_action is None:
        return None
    evidence.cached = True
    return evidence


def save_evidence(evidence: CompanyEvidence) -> None:
    path = _cache_path(evidence.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = evidence.to_dict()
    payload["cached"] = False
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _evidence_from_dict(raw: dict[str, Any], name: str) -> CompanyEvidence:
    return CompanyEvidence(
        symbol=str(raw.get("symbol", "")),
        name=name or str(raw.get("name", "")),
        filings=[FilingRecord(**item) for item in raw.get("filings", [])],
        news=[NewsItem(**item) for item in raw.get("news", [])],
        social=[SocialPost(**item) for item in raw.get("social", [])],
        price_action=_price_action_from_dict(raw.get("price_action")),
        errors=list(raw.get("errors", [])),
        fetched_at=str(raw.get("fetched_at", "")),
        cached=False,
    )


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(text.split())


def _sentiment_label(score: float) -> str:
    if score > 0.05:
        return "positive"
    if score < -0.05:
        return "negative"
    return "mixed"


class FilingsAgent:
    """Last five years of yearly and quarterly SEC reports for one company."""

    def collect(self, symbol: str, name: str) -> tuple[list[FilingRecord], str | None]:
        try:
            cik = _cik_for_ticker(symbol)
            if not cik:
                return [], f"No SEC company record for {symbol}. Filings were not fetched."
            filings = _filings_for_cik(symbol, cik)
            if not filings:
                return [], f"No 10-K, 10-Q, 20-F, or 6-K filings in the last 5 years for {symbol}."
            return filings, None
        except Exception as exc:
            logger.warning("Filings lookup failed for %s: %s", symbol, exc)
            return [], f"Filings lookup failed for {symbol}: {exc}"


class NewsAgent:
    """Recent headlines for one company from a public news search feed."""

    def collect(self, symbol: str, name: str) -> tuple[list[NewsItem], str | None]:
        try:
            query = f"{symbol} when:90d"
            url = NEWS_RSS + "?" + urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            raw = get_bytes(url, BROWSER_HEADERS, timeout=30)
            items = _parse_news_rss(symbol, raw.decode("utf-8", errors="replace"))
            if not items:
                return [], f"No recent news items found for {symbol}."
            return items[:NEWS_LIMIT], None
        except Exception as exc:
            logger.warning("News lookup failed for %s: %s", symbol, exc)
            return [], f"News lookup failed for {symbol}: {exc}"


class SocialAgent:
    """Recent X posts for one company, scored with the keyword sentiment scanner."""

    def __init__(self, sentiment: SentimentAnalysis | None = None):
        self.sentiment = sentiment or SentimentAnalysis()

    def collect(self, symbol: str, name: str) -> tuple[list[SocialPost], str | None]:
        token = env_secret("X_BEARER_TOKEN") or env_secret("TWITTER_BEARER_TOKEN")
        if not token:
            return [], "Social lookup skipped: set X_BEARER_TOKEN to read posts from X."
        try:
            posts = _search_x(symbol, name, token, self.sentiment)
            if not posts:
                return [], f"No recent X posts found for {symbol}."
            return posts[:SOCIAL_LIMIT], None
        except Exception as exc:
            logger.warning("Social lookup failed for %s: %s", symbol, exc)
            return [], f"Social lookup failed for {symbol}: {exc}"


def _price_action_from_dict(raw: dict[str, Any] | None) -> PriceActionSummary | None:
    if not raw:
        return None
    highs = [SwingPoint(**point) for point in raw.get("swing_highs") or []]
    lows = [SwingPoint(**point) for point in raw.get("swing_lows") or []]
    fields = {
        key: value
        for key, value in raw.items()
        if key not in {"swing_highs", "swing_lows"}
    }
    return PriceActionSummary(**fields, swing_highs=highs, swing_lows=lows)


def collect_evidence(symbol: str, name: str, use_cache: bool = True) -> CompanyEvidence:
    """Run filings, news, price action, and social agents together."""
    if use_cache:
        cached = load_cached_evidence(symbol, name)
        if cached is not None:
            return cached

    from concurrent.futures import ThreadPoolExecutor

    filings_agent = FilingsAgent()
    news_agent = NewsAgent()
    price_agent = PriceActionAgent()
    social_agent = SocialAgent()
    with ThreadPoolExecutor(max_workers=4) as pool:
        filings_future = pool.submit(filings_agent.collect, symbol, name)
        news_future = pool.submit(news_agent.collect, symbol, name)
        price_future = pool.submit(price_agent.collect, symbol, name)
        social_future = pool.submit(social_agent.collect, symbol, name)
        filings, filings_error = filings_future.result()
        news, news_error = news_future.result()
        price_action, price_error = price_future.result()
        social, social_error = social_future.result()

    evidence = CompanyEvidence(
        symbol=symbol,
        name=name,
        filings=filings,
        news=news,
        social=social,
        price_action=price_action,
        errors=[error for error in (filings_error, news_error, price_error, social_error) if error],
        fetched_at=datetime.now().replace(microsecond=0).isoformat(),
        cached=False,
    )
    save_evidence(evidence)
    return evidence


def evidence_brief(evidence: CompanyEvidence) -> str:
    """Compact text the signal model can read: filing excerpts, headlines, and posts."""
    lines = [f"Company: {evidence.name} ({evidence.symbol})"]
    if evidence.price_action is not None:
        lines.append(evidence.price_action.brief())
    else:
        lines.append("Price action: none")
    yearly = next((row for row in evidence.filings if row.form in {"10-K", "20-F"}), None)
    quarterly = next((row for row in evidence.filings if row.form in {"10-Q", "6-K"}), None)
    lines.append("Filings:")
    if not evidence.filings:
        lines.append("- none")
    else:
        for row in evidence.filings[:12]:
            lines.append(f"- {row.form} period {row.period_end} filed {row.filed_at} ({row.source})")
        for row in (yearly, quarterly):
            if row is None:
                continue
            excerpt = _filing_excerpt(row.url)
            if excerpt:
                lines.append(f"Excerpt from {row.form} filed {row.filed_at}:")
                lines.append(excerpt)
    lines.append("News:")
    if not evidence.news:
        lines.append("- none")
    else:
        for item in evidence.news[:NEWS_LIMIT]:
            summary = item.summary[:240]
            lines.append(f"- {item.published_at} | {item.source} | {item.title} | {summary}")
    lines.append("Social posts:")
    if not evidence.social:
        lines.append("- none")
    else:
        for post in evidence.social[:SOCIAL_LIMIT]:
            lines.append(
                f"- {post.posted_at} | @{post.author} | {post.sentiment} {post.score:.2f} | {post.text[:280]}"
            )
    return "\n".join(lines)


def _filing_excerpt(url: str, limit: int = 2200) -> str:
    try:
        raw = get_bytes(url, SEC_HEADERS, timeout=40)
    except Exception as exc:
        logger.warning("Filing excerpt failed for %s: %s", url, exc)
        return ""
    text = html.unescape(_strip_html(raw.decode("utf-8", errors="replace")))
    lowered = text.lower()
    start = lowered.rfind("item 7.")
    if start < 0:
        cursor = 0
        while True:
            found = lowered.find("item 2.", cursor)
            if found < 0:
                break
            if "management" in lowered[found:found + 90]:
                start = found
            cursor = found + 7
    if start < 0:
        return text[:limit]
    return text[start:start + limit]


def _load_ticker_map() -> dict[str, dict[str, str]]:
    global _ticker_map
    if _ticker_map is not None:
        return _ticker_map
    path = RESEARCH_DIR / "_sec_tickers.json"
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(cached["fetched_at"])
            if datetime.now() - fetched <= timedelta(days=7):
                _ticker_map = cached["tickers"]
                return _ticker_map
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            pass
    raw = json.loads(get_bytes(SEC_TICKER_URL, SEC_HEADERS).decode("utf-8"))
    tickers: dict[str, dict[str, str]] = {}
    for row in raw.values():
        symbol = str(row.get("ticker", "")).upper().replace(".", "-")
        if not symbol:
            continue
        tickers[symbol] = {
            "cik": str(int(row["cik_str"])).zfill(10),
            "title": str(row.get("title", "")),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fetched_at": datetime.now().replace(microsecond=0).isoformat(), "tickers": tickers}),
        encoding="utf-8",
    )
    _ticker_map = tickers
    return tickers


def _cik_for_ticker(symbol: str) -> str | None:
    return _load_ticker_map().get(symbol.upper(), {}).get("cik")


def _filings_for_cik(symbol: str, cik: str) -> list[FilingRecord]:
    payload = json.loads(get_bytes(SEC_SUBMISSIONS.format(cik=cik), SEC_HEADERS).decode("utf-8"))
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filed = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    cutoff = (date.today() - timedelta(days=365 * 5)).isoformat()
    cik_int = str(int(cik))
    rows: list[FilingRecord] = []
    for form, filed_at, period_end, accession, document in zip(forms, filed, periods, accessions, documents):
        if form not in FILING_FORMS or not filed_at or filed_at < cutoff:
            continue
        accession_path = str(accession).replace("-", "")
        url = SEC_ARCHIVES.format(cik=cik_int, accession=accession_path, document=document)
        rows.append(FilingRecord(
            symbol=symbol,
            form=str(form),
            period_end=str(period_end or ""),
            filed_at=str(filed_at),
            source="SEC EDGAR",
            url=url,
        ))
    rows.sort(key=lambda item: item.filed_at, reverse=True)
    yearly = [row for row in rows if row.form in {"10-K", "20-F"}]
    quarterly = [row for row in rows if row.form in {"10-Q", "6-K"}]
    return (yearly + quarterly)[:FILING_LIMIT]


def _parse_news_rss(symbol: str, xml_text: str) -> list[NewsItem]:
    if "<rss" not in xml_text.lower() and "<feed" not in xml_text.lower():
        raise ValueError("news feed did not return RSS")
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []
    for node in root.findall("./channel/item"):
        title = _strip_html(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None and source_node.text else ""
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        elif not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        summary = _strip_html(node.findtext("description") or "")
        items.append(NewsItem(
            symbol=symbol,
            title=title.strip(),
            source=source or "Google News",
            published_at=(node.findtext("pubDate") or "").strip(),
            url=link,
            summary=summary[:400],
        ))
    return items


def _search_x(symbol: str, name: str, token: str, sentiment: SentimentAnalysis) -> list[SocialPost]:
    safe_name = name.replace('"', "").strip() or symbol
    query = f'(${symbol} OR "{safe_name}") -is:retweet lang:en'
    url = X_SEARCH + "?" + urlencode({
        "query": query,
        "max_results": str(SOCIAL_LIMIT),
        "tweet.fields": "created_at,author_id",
        "expansions": "author_id",
        "user.fields": "username",
    })
    raw = get_bytes(url, {
        "Authorization": f"Bearer {token}",
        "User-Agent": SEC_HEADERS["User-Agent"],
        "Accept": "application/json",
    })
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("errors") and not payload.get("data"):
        detail = payload["errors"][0].get("message") or payload["errors"][0].get("title") or "X API error"
        raise RuntimeError(detail)
    users = {
        user.get("id"): user.get("username") or ""
        for user in payload.get("includes", {}).get("users", [])
    }
    posts: list[SocialPost] = []
    for tweet in payload.get("data", []):
        text = str(tweet.get("text", "")).strip()
        score = sentiment.analyze(text).score
        author_id = str(tweet.get("author_id", ""))
        username = users.get(author_id) or author_id or "unknown"
        tweet_id = str(tweet.get("id", ""))
        posts.append(SocialPost(
            symbol=symbol,
            author=username,
            text=text,
            posted_at=str(tweet.get("created_at", "")),
            url=f"https://x.com/{username}/status/{tweet_id}" if tweet_id else "",
            sentiment=_sentiment_label(score),
            score=score,
        ))
    return posts
