"""Decision policy (CONTRACTS §9): tolerances and thresholds the checks and the decision read."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.models.common import Dec, Money


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tolerances(_Section):
    unit_price_pct: Dec
    header_pct: Dec
    header_abs: Money
    rounding_abs: Money
    misc_charge_abs: Money
    qty_pct: Dec


class Approval(_Section):
    auto_approve_limit: Money


class POInference(_Section):
    auto_accept_inferred: bool
    min_score: float
    min_margin: float


class Duplicates(_Section):
    window_days: int
    fuzzy_similarity: float
    fuzzy_amount_pct: Dec
    fuzzy_date_window_days: int


class ExtractionPolicy(_Section):
    min_confidence_critical: float


class Dates(_Section):
    max_age_days: int
    order: str


class Policy(_Section):
    version: str
    tolerances: Tolerances
    approval: Approval
    po_inference: POInference
    duplicates: Duplicates
    extraction: ExtractionPolicy
    dates: Dates

    def canonical_dump(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @property
    def policy_version(self) -> str:
        """`version` + first 8 hex of sha256 of the canonical dump."""
        digest = hashlib.sha256(self.canonical_dump().encode("utf-8")).hexdigest()[:8]
        return f"{self.version}+{digest}"


def _read_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"policy file {path} must hold a mapping")
    # YAML floats → strings, so money and percentages stay exact Decimals.
    return json.loads(json.dumps(data), parse_float=str)


def load_policy(path: Path | None = None) -> Policy:
    """Read the policy YAML (default `POLICY_PATH`)."""
    return Policy.model_validate(_read_yaml(path or get_settings().policy_path))
