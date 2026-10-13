"""Concrete analysis modules for the trading analyst workflow.

These are lightweight, deterministic modules that do not require a live LLM.
They can later be wrapped by AGNO/Phidata agents or replaced with LLM-backed
implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class SignalResult:
    module: str
    score: float
    summary: str
    key_points: List[str] = field(default_factory=list)


class FundamentalAnalysis:
    """Simple keyword-based fundamental analyst.

    In production, this can ingest 10-K/10-Q, earnings calls, filings, and news.
    """

    def analyze(self, text: str) -> SignalResult:
        text_l = text.lower()
        positives = [
            "revenue growth", "earnings beat", "margin expansion", "cash flow",
            "guidance upgrade", "strong demand", "profitability", "operational leverage"
        ]
        negatives = [
            "margin pressure", "guidance cut", "demand slowdown", "legal risk",
            "inventory issue", "cost inflation", "revenue miss", "weak outlook"
        ]

        pos_hits = sum(1 for p in positives if p in text_l)
        neg_hits = sum(1 for n in negatives if n in text_l)
        score = max(-1.0, min(1.0, (pos_hits - neg_hits) / max(1, pos_hits + neg_hits + 1)))

        key_points = []
        if pos_hits:
            key_points.append("Positive operating signals detected from the document.")
        if neg_hits:
            key_points.append("Negative risk factors or weaker guidance are noted.")
        if not key_points:
            key_points.append("No explicit fundamental signal keywords were identified.")

        summary = (
            "Fundamental analysis suggests a " +
            ("bullish" if score > 0 else "neutral-to-cautious" if score == 0 else "bearish") +
            " bias based on the language in the supplied company and earnings context."
        )
        return SignalResult("fundamental", round(score, 3), summary, key_points)


class TechnicalAnalysis:
    """Simple technical readout using common price-pattern keywords."""

    def analyze(self, text: str) -> SignalResult:
        text_l = text.lower()
        bullish_terms = ["breakout", "support", "momentum", "uptrend", "continuation", "relative strength"]
        bearish_terms = ["breakdown", "resistance", "downtrend", "weakness", "distribution", "volatility spike"]

        pos_hits = sum(1 for t in bullish_terms if t in text_l)
        neg_hits = sum(1 for t in bearish_terms if t in text_l)
        score = max(-1.0, min(1.0, (pos_hits - neg_hits) / max(1, pos_hits + neg_hits + 1)))

        summary = (
            "Technical view is " + ("bullish" if score > 0 else "neutral" if score == 0 else "bearish") +
            " based on trend and breakout language in the analysis context."
        )
        key_points = []
        if pos_hits:
            key_points.append("Trend and breakout language supports upside continuation.")
        if neg_hits:
            key_points.append("Resistance or breakdown language indicates caution.")
        if not key_points:
            key_points.append("No explicit technical signal terms were found.")

        return SignalResult("technical", round(score, 3), summary, key_points)


class SentimentAnalysis:
    """Simple sentiment scanner for textual tone."""

    def analyze(self, text: str) -> SignalResult:
        text_l = text.lower()
        positive_words = [
            "strong", "optimistic", "positive", "excited", "confidence", "ahead", "robust",
            "upbeat", "excellent", "healthy", "surge", "beat", "accelerating"
        ]
        negative_words = [
            "weak", "concern", "negative", "risk", "worry", "pessimistic", "decline",
            "miss", "soft", "challenge", "pressure", "uncertain", "volatility"
        ]

        pos_hits = sum(1 for word in positive_words if word in text_l)
        neg_hits = sum(1 for word in negative_words if word in text_l)
        score = max(-1.0, min(1.0, (pos_hits - neg_hits) / max(1, pos_hits + neg_hits + 1)))

        summary = (
            "Sentiment is " + ("positive" if score > 0 else "mixed" if score == 0 else "negative") +
            " based on tone analysis of the supplied text."
        )
        key_points = []
        if pos_hits:
            key_points.append("Positive sentiment terms dominate the narrative.")
        if neg_hits:
            key_points.append("Negative risk and caution language is present.")
        if not key_points:
            key_points.append("Tone appears broadly neutral.")

        return SignalResult("sentiment", round(score, 3), summary, key_points)


class AnalystPipeline:
    """Pipeline that runs the major analysis modules in a deterministic sequence."""

    def __init__(self):
        self.fundamental = FundamentalAnalysis()
        self.technical = TechnicalAnalysis()
        self.sentiment = SentimentAnalysis()

    def analyze(self, text: str) -> Dict[str, Any]:
        fundamental = self.fundamental.analyze(text)
        technical = self.technical.analyze(text)
        sentiment = self.sentiment.analyze(text)
        weighted = (fundamental.score * 0.45) + (technical.score * 0.35) + (sentiment.score * 0.20)

        overall_bias = "bullish" if weighted > 0.2 else "bearish" if weighted < -0.2 else "neutral"
        return {
            "overall_bias": overall_bias,
            "overall_score": round(weighted, 3),
            "modules": {
                "fundamental": fundamental.__dict__,
                "technical": technical.__dict__,
                "sentiment": sentiment.__dict__,
            },
        }
