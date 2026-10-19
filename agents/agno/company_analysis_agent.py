"""Company analysis agent.

Runs the filings, news, price-action, and social agents, then asks the
selected LLM for one signal per company: long, short, or flat.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from agents.agno import llm as llm_runtime
from agents.agno.research_agents import CompanyEvidence, collect_evidence, evidence_brief

MAX_COMPANIES = 10
ProgressFn = Callable[[int, int, str], None]
ReportFn = Callable[["AnalysisReport"], None]
logger = logging.getLogger(__name__)


@dataclass
class CompanyRequest:
    symbol: str
    name: str
    indexes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CompanyRequest":
        indexes = raw.get("indexes", [])
        if isinstance(indexes, str):
            indexes = [part.strip() for part in indexes.split(",") if part.strip()]
        return cls(
            symbol=str(raw.get("symbol", "")).strip().upper(),
            name=str(raw.get("name", "")).strip() or str(raw.get("symbol", "")).strip().upper(),
            indexes=list(indexes),
        )


@dataclass
class CompanySignal:
    """One company's signal. `signal` is long, short, flat, or pending when scoring failed."""

    symbol: str
    name: str
    indexes: list[str]
    signal: str
    confidence: float | None
    rationale: str
    status: str = "template"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisReport:
    status: str
    llm_called: bool
    company_count: int
    signals: list[CompanySignal]
    evidence: list[CompanyEvidence]
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


class CompanyAnalysisAgent:
    """Basket-level entry point used by the Companies page.

    `analyze` runs the filings, news, price-action, and social agents together,
    then scores each company with the selected model.
    """

    def analyze(
        self,
        companies: Iterable[CompanyRequest | Mapping[str, Any]],
        *,
        use_cache: bool = True,
        provider: str | None = None,
        model: str | None = None,
        progress: ProgressFn | None = None,
        on_update: ReportFn | None = None,
    ) -> AnalysisReport:
        requests = [_coerce(company) for company in companies]
        requests = [company for company in requests if company.symbol][:MAX_COMPANIES]
        choice = llm_runtime.LLMChoice(
            (provider or llm_runtime.DEFAULT_CHOICE_PROVIDER).strip().lower(),
            (model or llm_runtime.DEFAULT_CHOICE_MODEL).strip(),
        )
        signals = [_queued_signal(company) for company in requests]
        evidence = [CompanyEvidence(symbol=company.symbol, name=company.name) for company in requests]
        active = ""

        def publish() -> AnalysisReport:
            report = _build_report(signals, evidence, choice, active)
            if on_update is not None:
                on_update(report)
            return report

        publish()
        total = len(requests)
        for index, company in enumerate(requests):
            active = company.symbol
            if progress:
                progress(index + 1, total, company.symbol)
            try:
                bundle = collect_evidence(company.symbol, company.name, use_cache=use_cache)
                signal = self._draft_signal(company, bundle, choice)
            except Exception as exc:
                logger.exception("Company analysis failed for %s", company.symbol)
                bundle = CompanyEvidence(
                    symbol=company.symbol,
                    name=company.name,
                    errors=[f"Research failed for {company.symbol}: {exc}"],
                    fetched_at=datetime.now().replace(microsecond=0).isoformat(),
                )
                signal = CompanySignal(
                    symbol=company.symbol,
                    name=company.name,
                    indexes=list(company.indexes),
                    signal="pending",
                    confidence=None,
                    rationale=f"Research failed for {company.symbol}: {exc}",
                    status="error",
                )
            evidence[index] = bundle
            signals[index] = signal
            publish()
        active = ""
        return publish()

    def _draft_signal(
        self,
        company: CompanyRequest,
        evidence: CompanyEvidence,
        choice: llm_runtime.LLMChoice,
    ) -> CompanySignal:
        price_action = evidence.price_action
        has_price = price_action is not None and not price_action.error
        has_evidence = bool(evidence.filings or evidence.news or evidence.social or has_price)
        if not has_evidence:
            return CompanySignal(
                symbol=company.symbol,
                name=company.name,
                indexes=list(company.indexes),
                signal="flat",
                confidence=0.0,
                rationale=(
                    f"No filings, news, social posts, or price bars were collected for {company.symbol}, "
                    "so the signal is flat."
                ),
                status="no_evidence",
            )
        prompt = _signal_prompt(evidence)
        raw = llm_runtime.generate(prompt, provider=choice.provider, model=choice.model, max_tokens=500)
        parsed = _parse_signal(raw)
        if parsed is None:
            detail = raw.strip() or "The model did not return a signal."
            return CompanySignal(
                symbol=company.symbol,
                name=company.name,
                indexes=list(company.indexes),
                signal="pending",
                confidence=None,
                rationale=detail[:800],
                status="error",
            )
        return CompanySignal(
            symbol=company.symbol,
            name=company.name,
            indexes=list(company.indexes),
            signal=parsed["signal"],
            confidence=parsed["confidence"],
            rationale=parsed["rationale"],
            status="scored",
        )


def _signal_prompt(evidence: CompanyEvidence) -> str:
    return (
        "You are a trading analyst. Use only the evidence below. "
        "Do not invent figures that are not in the evidence.\n"
        "Price action numbers were computed from OHLCV bars by the price-action agent. "
        "In the rationale, state the trend, where the last close sits versus recent swings, "
        "and what would confirm or fail that move. Then weigh filings, news, and social posts.\n"
        "Choose one signal:\n"
        "- long: price structure and the other evidence lean positive\n"
        "- short: they lean negative\n"
        "- flat: the evidence is mixed, thin, or not enough to take a side\n"
        "Reply with JSON only, no markdown:\n"
        '{"signal":"flat","confidence":0.5,"rationale":"two to four sentences"}\n'
        "confidence is a number from 0 to 1.\n\n"
        f"{evidence_brief(evidence)}\n"
    )


def _parse_signal(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text or text.startswith("LLM error:"):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    signal = str(payload.get("signal", "")).strip().lower()
    if signal not in {"long", "short", "flat"}:
        return None
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    rationale = re.sub(r"\s+", " ", str(payload.get("rationale", "")).strip())
    if not rationale:
        rationale = f"The model returned {signal} without a written rationale."
    return {"signal": signal, "confidence": round(confidence, 2), "rationale": rationale[:800]}


def _queued_signal(company: CompanyRequest) -> CompanySignal:
    return CompanySignal(
        symbol=company.symbol,
        name=company.name,
        indexes=list(company.indexes),
        signal="pending",
        confidence=None,
        rationale="Waiting to research this company.",
        status="queued",
    )


def _build_report(
    signals: list[CompanySignal],
    evidence: list[CompanyEvidence],
    choice: llm_runtime.LLMChoice,
    active: str,
) -> AnalysisReport:
    scored = sum(signal.status == "scored" for signal in signals)
    queued = sum(signal.status == "queued" for signal in signals)
    finished = len(signals) - queued
    if not signals:
        note = "No companies were submitted."
        status = "empty"
    elif queued:
        working = f" Working on {active}." if active else ""
        note = f"{finished} of {len(signals)} companies finished.{working} Results appear as each company completes."
        status = "running"
    elif scored == len(signals):
        note = f"Signals scored with {choice.label}. This is research output, not an order."
        status = "signaled"
    elif scored:
        note = (
            f"{scored} of {len(signals)} companies scored with {choice.label}. "
            "The others stayed pending because the model call failed or there was no evidence."
        )
        status = "partial"
    else:
        note = f"No signal was scored. Check the model credentials for {choice.label}."
        status = "unscored"
    return AnalysisReport(
        status=status,
        llm_called=scored > 0,
        company_count=len(signals),
        signals=signals,
        evidence=evidence,
        note=note,
    )


def _coerce(company: CompanyRequest | Mapping[str, Any]) -> CompanyRequest:
    if isinstance(company, CompanyRequest):
        return company
    return CompanyRequest.from_mapping(company)
