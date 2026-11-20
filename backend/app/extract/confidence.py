"""Per-field confidence in integer points (CONTRACTS §11), reported as 0–1."""

from __future__ import annotations

from app.enums import ConfidenceLevel

from .grounding import Grounded

BASE = 20
GROUND_POINTS: dict[str, int] = {"exact": 45, "fuzzy": 25, "none": 0, "unavailable": 25}
VALIDATOR_POINTS = 35
HUMAN_VERIFIED = 100


def level_for(points: int) -> ConfidenceLevel:
    if points >= 80:
        return ConfidenceLevel.high
    if points >= 60:
        return ConfidenceLevel.medium
    return ConfidenceLevel.low


def points(grounded: Grounded, validator_passed: bool) -> int:
    return min(100, BASE + GROUND_POINTS[grounded] + (VALIDATOR_POINTS if validator_passed else 0))


def score(grounded: Grounded, validator_passed: bool) -> tuple[float, ConfidenceLevel]:
    pts = points(grounded, validator_passed)
    return pts / 100, level_for(pts)


def missing() -> tuple[float, ConfidenceLevel]:
    return 0.0, ConfidenceLevel.low
