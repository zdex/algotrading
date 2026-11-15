"""Trading desk orchestrated by a LangGraph StateGraph.

Web, fundamental, social, and technical agents run in parallel. Each hands its
packet to its own signal agent. Those four signals join at the decision agent.
The execution agent queues a paper order only when the sources agree. Orders
are written to the local blotter and are not sent to a broker.
"""
from __future__ import annotations

import json
import operator
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.agno.analysis_agents import FundamentalAnalysis, SentimentAnalysis
from agents.agno.config import ROOT

MAX_COMPANIES = 5
AGENT_NAMES = (
    "Web agent",
    "Web signal agent",
    "Fundamental agent",
    "Fundamental signal agent",
    "Social agent",
    "Social signal agent",
    "Technical agent",
    "Technical signal agent",
    "Decision agent",
    "Execution agent",
)
RESEARCH_AGENTS = ("Web agent", "Fundamental agent", "Social agent", "Technical agent")
DEFAULT_ORDERS = ROOT / "data" / "agents" / "paper_orders.json"
_AGREE = 0.05
_ORDER_LOCKS: dict[str, threading.Lock] = {}
_ORDER_LOCKS_GUARD = threading.Lock()

ProgressFn = Callable[["DeskState"], None]


def _orders_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _ORDER_LOCKS_GUARD:
        lock = _ORDER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ORDER_LOCKS[key] = lock
        return lock


class GraphState(TypedDict):
    symbol: str
    name: str
    sector: str
    web: WebPacket
    fundamental: FundamentalPacket
    social: SocialPacket
    technical: TechnicalPacket
    signals: Annotated[list[Signal], operator.add]
    log: Annotated[list[DeskLog], operator.add]
    decision: DeskDecision | None
    order: PaperOrder | None


@dataclass
class DeskCompany:
    symbol: str
    name: str
    sector: str = ""


@dataclass
class WebPacket:
    headlines: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class FundamentalPacket:
    documents: list[str] = field(default_factory=list)
    text: str = ""
    excerpt_found: bool = False
    error: str | None = None


@dataclass
class SocialPacket:
    posts: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    error: str | None = None


@dataclass
class TechnicalPacket:
    brief: str = ""
    trend: str = "unknown"
    breakout: str = "none"
    last_close: float | None = None
    support: float | None = None
    resistance: float | None = None
    gap_pct: float | None = None
    volume_vs_average: float | None = None
    bars: int = 0
    error: str | None = None


@dataclass
class Signal:
    agent: str
    symbol: str
    stance: str
    score: float
    summary: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeskDecision:
    symbol: str
    action: str
    qty: int
    reason: str
    signals: list[Signal]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        return payload


@dataclass
class PaperOrder:
    symbol: str
    side: str
    qty: int
    reason: str
    status: str
    submitted_at: str
    route: str = "paper blotter"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeskLog:
    agent: str
    symbol: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeskState:
    roster: dict[str, str]
    detail: dict[str, str]
    log: list[DeskLog] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    decisions: list[DeskDecision] = field(default_factory=list)
    orders: list[PaperOrder] = field(default_factory=list)
    on_update: ProgressFn | None = None

    def to_dict(self) -> dict:
        return {
            "roster": [
                {"agent": name, "status": self.roster[name], "detail": self.detail[name]}
                for name in AGENT_NAMES
            ],
            "log": [line.to_dict() for line in self.log],
            "signals": [signal.to_dict() for signal in self.signals],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "orders": [order.to_dict() for order in self.orders],
        }


def _stance(score: float) -> str:
    if score > _AGREE:
        return "buy"
    if score < -_AGREE:
        return "sell"
    return "flat"


def combine_signals(signals: list[Signal]) -> tuple[str, int, str]:
    """Trade only when at least two sources agree and none oppose."""
    buys = [signal for signal in signals if signal.stance == "buy"]
    sells = [signal for signal in signals if signal.stance == "sell"]
    parts = [f"{signal.agent} {signal.stance} {signal.score:+.2f}" for signal in signals]
    summary = "; ".join(parts)
    if len(buys) >= 2 and not sells:
        qty = _agreement_qty(len(buys))
        return "buy", qty, f"{summary}. {len(buys)} sources agree on buy and none oppose."
    if len(sells) >= 2 and not buys:
        qty = _agreement_qty(len(sells))
        return "sell", qty, f"{summary}. {len(sells)} sources agree on sell and none oppose."
    return "hold", 0, f"{summary}. No trade: the sources do not agree."


def _agreement_qty(votes: int) -> int:
    if votes >= 4:
        return 20
    if votes == 3:
        return 15
    return 10


def score_technical(packet: TechnicalPacket) -> tuple[float, list[str]]:
    """Turn trend, breakout, gap, and volume into one score from -1 to 1."""
    points: list[str] = []
    score = 0.0
    if packet.trend == "uptrend":
        score += 0.45
        points.append("Swing highs and lows are an uptrend.")
    elif packet.trend == "downtrend":
        score -= 0.45
        points.append("Swing highs and lows are a downtrend.")
    else:
        points.append(f"Swing structure is {packet.trend}.")
    if packet.breakout == "above_prior_range":
        score += 0.35
        points.append("Close is above the prior 20-bar range.")
    elif packet.breakout == "below_prior_range":
        score -= 0.35
        points.append("Close is below the prior 20-bar range.")
    else:
        points.append("No range breakout.")
    if packet.volume_vs_average is not None and packet.volume_vs_average >= 1.2 and packet.breakout != "none":
        score += 0.1 if packet.breakout == "above_prior_range" else -0.1
        points.append(f"Volume is {packet.volume_vs_average:.2f}x the 20-bar average.")
    if packet.gap_pct is not None and abs(packet.gap_pct) >= 0.5:
        score += 0.1 if packet.gap_pct > 0 else -0.1
        points.append(f"Latest gap is {packet.gap_pct:.2f}%.")
    return round(max(-1.0, min(1.0, score)), 3), points


def collect_web(company: DeskCompany) -> WebPacket:
    from agents.agno.research_agents import NewsAgent

    items, error = NewsAgent().collect(company.symbol, company.name)
    headlines = [
        " | ".join(part for part in (item.published_at, item.source, item.title, item.summary) if part)
        for item in items
    ]
    return WebPacket(headlines=headlines, error=error)


def collect_fundamental(company: DeskCompany) -> FundamentalPacket:
    from agents.agno.research_agents import FilingsAgent, _filing_excerpt

    filings, error = FilingsAgent().collect(company.symbol, company.name)
    documents = [
        f"{row.form} period {row.period_end} filed {row.filed_at} ({row.source})"
        for row in filings[:8]
    ]
    excerpts: list[str] = []
    latest = next((row for row in filings if row.form in {"10-Q", "6-K"}), None)
    yearly = next((row for row in filings if row.form in {"10-K", "20-F"}), None)
    for row in (latest, yearly):
        if row is None:
            continue
        excerpt = _filing_excerpt(row.url, limit=1600)
        if excerpt:
            excerpts.append(f"Excerpt from {row.form} filed {row.filed_at}:\n{excerpt}")
    text = "\n".join(documents + excerpts)
    return FundamentalPacket(
        documents=documents,
        text=text,
        excerpt_found=bool(excerpts),
        error=error,
    )


def collect_technical(company: DeskCompany) -> TechnicalPacket:
    from agents.agno.price_action import PriceActionAgent

    summary, error = PriceActionAgent().collect(company.symbol, company.name)
    return TechnicalPacket(
        brief=summary.brief(),
        trend=summary.trend,
        breakout=summary.breakout,
        last_close=summary.last_close,
        support=summary.support,
        resistance=summary.resistance,
        gap_pct=summary.gap_pct,
        volume_vs_average=summary.volume_vs_average,
        bars=summary.bars,
        error=error,
    )


def collect_social(company: DeskCompany) -> SocialPacket:
    from agents.agno.research_agents import SocialAgent

    posts, error = SocialAgent().collect(company.symbol, company.name)
    return SocialPacket(
        posts=[f"@{post.author} ({post.sentiment} {post.score:+.2f}): {post.text}" for post in posts],
        scores=[float(post.score) for post in posts],
        error=error,
    )


class TradingDesk:
    def __init__(
        self,
        web: Callable[[DeskCompany], WebPacket] | None = None,
        fundamental: Callable[[DeskCompany], FundamentalPacket] | None = None,
        social: Callable[[DeskCompany], SocialPacket] | None = None,
        technical: Callable[[DeskCompany], TechnicalPacket] | None = None,
        orders_path: Path | None = None,
    ):
        self.web = web or collect_web
        self.fundamental = fundamental or collect_fundamental
        self.social = social or collect_social
        self.technical = technical or collect_technical
        self.orders_path = orders_path
        self._sentiment = SentimentAnalysis()
        self._fundamental = FundamentalAnalysis()
        self.graph = self._build_graph()

    def run(self, companies: list[DeskCompany], on_update: ProgressFn | None = None) -> DeskState:
        if len(companies) > MAX_COMPANIES:
            raise ValueError(f"The trading agent accepts {MAX_COMPANIES} companies at a time.")
        state = DeskState(
            roster={name: "idle" for name in AGENT_NAMES},
            detail={name: "Waiting" for name in AGENT_NAMES},
            on_update=on_update,
        )
        self._touch(state)
        total = len(companies)
        for index, company in enumerate(companies, start=1):
            detail = f"{company.symbol} · {index}/{total}"
            research_marked = False
            for mode, chunk in self.graph.stream(_graph_input(company), stream_mode=["tasks", "updates"]):
                if mode == "tasks":
                    research_marked = self._on_task(state, chunk, detail, research_marked)
                elif mode == "updates":
                    self._on_update_chunk(state, chunk)
        return state

    def _build_graph(self):
        graph = StateGraph(GraphState)
        graph.add_node("Web agent", self._node_web)
        graph.add_node("Fundamental agent", self._node_fundamental)
        graph.add_node("Social agent", self._node_social)
        graph.add_node("Technical agent", self._node_technical)
        graph.add_node("Web signal agent", self._node_web_signal)
        graph.add_node("Fundamental signal agent", self._node_fundamental_signal)
        graph.add_node("Social signal agent", self._node_social_signal)
        graph.add_node("Technical signal agent", self._node_technical_signal)
        graph.add_node("Decision agent", self._node_decision)
        graph.add_node("Execution agent", self._node_execution)
        for name in RESEARCH_AGENTS:
            graph.add_edge(START, name)
        graph.add_edge("Web agent", "Web signal agent")
        graph.add_edge("Fundamental agent", "Fundamental signal agent")
        graph.add_edge("Social agent", "Social signal agent")
        graph.add_edge("Technical agent", "Technical signal agent")
        for name in ("Web signal agent", "Fundamental signal agent", "Social signal agent", "Technical signal agent"):
            graph.add_edge(name, "Decision agent")
        graph.add_edge("Decision agent", "Execution agent")
        graph.add_edge("Execution agent", END)
        return graph.compile()

    def _on_task(self, state: DeskState, chunk: dict, detail: str, research_marked: bool) -> bool:
        name = str(chunk.get("name") or "")
        if name not in AGENT_NAMES or "result" in chunk or "error" in chunk:
            return research_marked
        if name in RESEARCH_AGENTS and not research_marked:
            for agent in RESEARCH_AGENTS:
                state.roster[agent] = "running"
                state.detail[agent] = detail
            research_marked = True
        else:
            state.roster[name] = "running"
            state.detail[name] = detail
        self._touch(state)
        return research_marked

    def _on_update_chunk(self, state: DeskState, chunk: dict) -> None:
        for name, payload in chunk.items():
            if name not in AGENT_NAMES or not isinstance(payload, dict):
                continue
            state.log.extend(payload.get("log") or [])
            state.signals.extend(payload.get("signals") or [])
            decision = payload.get("decision")
            if isinstance(decision, DeskDecision):
                state.decisions.append(decision)
            order = payload.get("order")
            if isinstance(order, PaperOrder):
                state.orders.append(order)
            symbol = next((line.symbol for line in payload.get("log") or [] if line.symbol), "")
            state.roster[name] = _node_status(name, payload)
            state.detail[name] = symbol or state.detail.get(name, "")
            self._touch(state)

    def _node_web(self, graph_state: GraphState) -> dict:
        company = _company(graph_state)
        packet = self._call(self.web, company, WebPacket)
        text = _lines(packet.headlines, packet.error)
        return {
            "web": packet,
            "log": [DeskLog("Web agent", company.symbol, text)],
        }

    def _node_fundamental(self, graph_state: GraphState) -> dict:
        company = _company(graph_state)
        packet = self._call(self.fundamental, company, FundamentalPacket)
        return {
            "fundamental": packet,
            "log": [DeskLog("Fundamental agent", company.symbol, _fundamental_text(packet))],
        }

    def _node_social(self, graph_state: GraphState) -> dict:
        company = _company(graph_state)
        packet = self._call(self.social, company, SocialPacket)
        return {
            "social": packet,
            "log": [DeskLog("Social agent", company.symbol, _lines(packet.posts, packet.error))],
        }

    def _node_technical(self, graph_state: GraphState) -> dict:
        company = _company(graph_state)
        packet = self._call(self.technical, company, TechnicalPacket)
        text = packet.brief or packet.error or "No price bars were returned."
        return {
            "technical": packet,
            "log": [DeskLog("Technical agent", company.symbol, text)],
        }

    def _node_web_signal(self, graph_state: GraphState) -> dict:
        packet = graph_state["web"]
        if not packet.headlines:
            signal = _flat_signal("Web signal agent", graph_state["symbol"], packet.error or "No web items were returned.", {"items": 0})
        else:
            result = self._sentiment.analyze("\n".join(packet.headlines))
            signal = _from_analysis("Web signal agent", graph_state["symbol"], result, {"items": len(packet.headlines)})
        return _signal_update(signal)

    def _node_fundamental_signal(self, graph_state: GraphState) -> dict:
        packet = graph_state["fundamental"]
        if not packet.text:
            signal = _flat_signal(
                "Fundamental signal agent",
                graph_state["symbol"],
                packet.error or "No quarterly report or P&L text was returned.",
                {"items": 0, "excerpt_found": False},
            )
        else:
            result = self._fundamental.analyze(packet.text)
            signal = _from_analysis(
                "Fundamental signal agent",
                graph_state["symbol"],
                result,
                {"items": len(packet.documents), "excerpt_found": packet.excerpt_found},
            )
        return _signal_update(signal)

    def _node_social_signal(self, graph_state: GraphState) -> dict:
        packet = graph_state["social"]
        if not packet.scores:
            signal = _flat_signal("Social signal agent", graph_state["symbol"], packet.error or "No social posts were returned.", {"items": 0})
        else:
            score = round(sum(packet.scores) / len(packet.scores), 3)
            signal = Signal(
                agent="Social signal agent",
                symbol=graph_state["symbol"],
                stance=_stance(score),
                score=score,
                summary=f"{len(packet.scores)} posts, average sentiment {score:+.2f}.",
                metadata={"items": len(packet.scores), "key_points": [f"Average of {len(packet.scores)} post scores."]},
            )
        return _signal_update(signal)

    def _node_technical_signal(self, graph_state: GraphState) -> dict:
        packet = graph_state["technical"]
        if packet.bars <= 0:
            signal = _flat_signal(
                "Technical signal agent",
                graph_state["symbol"],
                packet.error or "No price bars were returned.",
                {"items": 0, "trend": packet.trend, "breakout": packet.breakout},
            )
        else:
            score, points = score_technical(packet)
            signal = Signal(
                agent="Technical signal agent",
                symbol=graph_state["symbol"],
                stance=_stance(score),
                score=score,
                summary=f"Technical view from {packet.bars} bars: trend {packet.trend}, breakout {packet.breakout}.",
                metadata={
                    "items": packet.bars,
                    "trend": packet.trend,
                    "breakout": packet.breakout,
                    "last_close": packet.last_close,
                    "support": packet.support,
                    "resistance": packet.resistance,
                    "key_points": points,
                },
            )
        return _signal_update(signal)

    def _node_decision(self, graph_state: GraphState) -> dict:
        signals = list(graph_state.get("signals") or [])
        action, qty, reason = combine_signals(signals)
        decision = DeskDecision(graph_state["symbol"], action, qty, reason, signals)
        meta = "; ".join(
            f"{signal.agent} items={signal.metadata.get('items', 0)} score={signal.score:+.2f}"
            for signal in signals
        )
        text = f"{action.upper()} {qty or ''}".strip() + f"\n{reason}\nMetadata: {meta}"
        return {
            "decision": decision,
            "log": [DeskLog("Decision agent", graph_state["symbol"], text)],
        }

    def _node_execution(self, graph_state: GraphState) -> dict:
        decision = graph_state["decision"]
        if decision is None or decision.action == "hold":
            reason = decision.reason if decision is not None else "No decision was produced."
            return {
                "order": None,
                "log": [DeskLog("Execution agent", graph_state["symbol"], f"No order. {reason}")],
            }
        order = PaperOrder(
            symbol=graph_state["symbol"],
            side=decision.action.upper(),
            qty=decision.qty,
            reason=decision.reason,
            status="queued",
            submitted_at=datetime.now().replace(microsecond=0).isoformat(),
        )
        self._persist(order)
        text = (
            f"Queued paper {order.side} {order.qty} {order.symbol}. "
            "This order stays on the paper blotter and is not sent to a broker.\n"
            f"{order.reason}"
        )
        return {"order": order, "log": [DeskLog("Execution agent", graph_state["symbol"], text)]}

    def _persist(self, order: PaperOrder) -> None:
        if self.orders_path is None:
            return
        with _orders_lock(self.orders_path):
            existing: list[dict] = []
            if self.orders_path.is_file():
                try:
                    loaded = json.loads(self.orders_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        existing = loaded
                except (OSError, json.JSONDecodeError):
                    existing = []
            existing.append(order.to_dict())
            self.orders_path.parent.mkdir(parents=True, exist_ok=True)
            self.orders_path.write_text(json.dumps(existing[-100:], indent=2), encoding="utf-8")

    def _touch(self, state: DeskState) -> None:
        if state.on_update is not None:
            state.on_update(state)

    @staticmethod
    def _call(fn, company: DeskCompany, empty):
        try:
            return fn(company)
        except Exception as exc:
            return empty(error=str(exc))


def _company(graph_state: GraphState) -> DeskCompany:
    return DeskCompany(graph_state["symbol"], graph_state["name"], graph_state.get("sector") or "")


def _graph_input(company: DeskCompany) -> GraphState:
    return {
        "symbol": company.symbol,
        "name": company.name,
        "sector": company.sector,
        "web": WebPacket(),
        "fundamental": FundamentalPacket(),
        "social": SocialPacket(),
        "technical": TechnicalPacket(),
        "signals": [],
        "log": [],
        "decision": None,
        "order": None,
    }


def _signal_text(signal: Signal) -> str:
    lines = [
        f"Stance {signal.stance} · score {signal.score:+.2f}",
        signal.summary,
    ]
    for point in signal.metadata.get("key_points", []):
        lines.append(f"- {point}")
    items = signal.metadata.get("items")
    if items is not None:
        lines.append(f"Metadata: items {items}, stance {signal.stance}, score {signal.score:+.2f}")
    return "\n".join(lines)


def _signal_update(signal: Signal) -> dict:
    return {"signals": [signal], "log": [DeskLog(signal.agent, signal.symbol, _signal_text(signal))]}


def _node_status(name: str, payload: dict) -> str:
    if name == "Web agent":
        packet = payload.get("web")
        if isinstance(packet, WebPacket) and packet.error and not packet.headlines:
            return "error"
    elif name == "Fundamental agent":
        packet = payload.get("fundamental")
        has_items = isinstance(packet, FundamentalPacket) and bool(packet.documents or packet.text)
        if isinstance(packet, FundamentalPacket) and packet.error and not has_items:
            return "error"
    elif name == "Social agent":
        packet = payload.get("social")
        if isinstance(packet, SocialPacket) and packet.error and not packet.posts:
            return "error"
    elif name == "Technical agent":
        packet = payload.get("technical")
        if isinstance(packet, TechnicalPacket) and packet.error and packet.bars <= 0:
            return "error"
    return "done"


def _flat_signal(agent: str, symbol: str, summary: str, metadata: dict) -> Signal:
    metadata = {**metadata, "key_points": [summary]}
    return Signal(agent, symbol, "flat", 0.0, summary, metadata)


def _from_analysis(agent: str, symbol: str, result, metadata: dict) -> Signal:
    metadata = {**metadata, "key_points": list(result.key_points)}
    return Signal(agent, symbol, _stance(result.score), round(float(result.score), 3), result.summary, metadata)


def _lines(items: list[str], error: str | None) -> str:
    if not items:
        return error or "Nothing returned."
    body = "\n".join(f"- {item}" for item in items[:8])
    if error:
        return f"{error}\n{body}"
    return body


def _fundamental_text(packet: FundamentalPacket) -> str:
    if not packet.documents and not packet.text:
        return packet.error or "No company filings were returned."
    lines = [f"- {line}" for line in packet.documents[:8]]
    if packet.excerpt_found:
        lines.append("Read management discussion from the latest quarterly or annual filing for the P&L language.")
    else:
        lines.append("Filing list is in. No statement text was extracted, so there is no P&L language to score yet.")
    if packet.error:
        lines.insert(0, packet.error)
    return "\n".join(lines)


def load_orders(path: Path | None = None) -> list[dict]:
    target = path or DEFAULT_ORDERS
    if not target.is_file():
        return []
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []
