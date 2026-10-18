"""Company analysis agent.

Phase 1 template. It accepts the companies a user selected and returns a
structured report with a placeholder signal for each name. It does not call
an LLM. A later phase will replace `_draft_signal` with model-backed
fundamental, technical, and sentiment work and emit long / short / flat signals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


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
    """One company's analysis output. `signal` stays `pending` until the LLM phase."""

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
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        return payload


class CompanyAnalysisAgent:
    """Basket-level analysis entry point used by the Companies page.

    `analyze` is the stable interface the UI calls. Signal generation is
    isolated in `_draft_signal` so the next phase can add an LLM without
    changing the page contract.
    """

    def analyze(self, companies: Iterable[CompanyRequest | Mapping[str, Any]]) -> AnalysisReport:
        requests = [_coerce(company) for company in companies]
        requests = [company for company in requests if company.symbol]
        signals = [self._draft_signal(company) for company in requests]
        return AnalysisReport(
            status="template",
            llm_called=False,
            company_count=len(signals),
            signals=signals,
            note=(
                "Template run only. No language model was called. "
                "Signals will be generated in a later phase."
            ),
        )

    def _draft_signal(self, company: CompanyRequest) -> CompanySignal:
        membership = ", ".join(company.indexes) if company.indexes else "selected index"
        return CompanySignal(
            symbol=company.symbol,
            name=company.name,
            indexes=list(company.indexes),
            signal="pending",
            confidence=None,
            rationale=(
                f"{company.name} ({company.symbol}) is queued for analysis "
                f"({membership}). Signal generation is not implemented yet."
            ),
            status="template",
        )


def _coerce(company: CompanyRequest | Mapping[str, Any]) -> CompanyRequest:
    if isinstance(company, CompanyRequest):
        return company
    return CompanyRequest.from_mapping(company)
