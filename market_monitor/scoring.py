"""Illustrative priority score. Not a forecast and not a trade signal."""

from __future__ import annotations

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

DEFAULT_THRESHOLDS = {"critical": 80.0, "high": 60.0}


def priority_score(
    impact: int,
    probability: int,
    exposure: int | None,
    urgency: int,
    reliability: int,
) -> tuple[float | None, str]:
    """Return (score 0-100, status).

    Status is ``complete``, ``partial`` when exposure is missing, or ``incomplete``
    when another input is missing. Missing exposure is left out of the weights.
    It is never filled in as zero.
    """
    required = (impact, probability, urgency, reliability)
    if any(value is None for value in required):
        return None, "incomplete"
    if exposure is None:
        weighted = 0.30 * impact + 0.15 * probability + 0.15 * urgency + 0.10 * reliability
        return 100 * weighted / (0.70 * 5), "partial"
    weighted = (
        0.30 * impact
        + 0.15 * probability
        + 0.30 * exposure
        + 0.15 * urgency
        + 0.10 * reliability
    )
    return 100 * weighted / 5, "complete"


def priority_band(score: float | None, thresholds: dict | None = None) -> str:
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)
    if score is None:
        return "unknown"
    if score >= float(limits["critical"]):
        return "critical review"
    if score >= float(limits["high"]):
        return "high priority"
    return "routine"


def exposure_bucket(weight_pct: float | None) -> int | None:
    if weight_pct is None:
        return None
    if weight_pct < 1:
        return 1
    if weight_pct < 3:
        return 2
    if weight_pct < 7:
        return 3
    if weight_pct < 12:
        return 4
    return 5
