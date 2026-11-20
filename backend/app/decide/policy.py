"""Decision policy (CONTRACTS §9): tolerances and thresholds the checks and the decision read."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

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
        """Key-sorted JSON with numbers normalised, so `10`, `10.0` and `"10.00"` hash alike."""
        return json.dumps(_canonical(self.model_dump()), sort_keys=True, separators=(",", ":"))

    @property
    def policy_version(self) -> str:
        """`version` + first 8 hex of sha256 of the canonical dump."""
        digest = hashlib.sha256(self.canonical_dump().encode("utf-8")).hexdigest()[:8]
        return f"{self.version}+{digest}"

    def with_overrides(self, overrides: Mapping[str, Any]) -> Policy:
        """A copy with values replaced. Keys are either sections with a mapping
        (`{"tolerances": {"unit_price_pct": 10}}`) or bare setting names that exist in exactly one
        section (`{"unit_price_pct": 10}`). Unknown keys raise `ValueError`."""
        data = self.model_dump(mode="json")
        sections = {k for k, v in data.items() if isinstance(v, dict)}
        for key, value in overrides.items():
            if key in sections:
                if not isinstance(value, Mapping):
                    raise ValueError(f"policy section {key!r} needs a mapping")
                for sub, sub_value in value.items():
                    if sub not in data[key]:
                        raise ValueError(f"unknown policy setting {key}.{sub}")
                    data[key][sub] = _plain(sub_value)
                continue
            owners = [s for s in sections if key in data[s]]
            if len(owners) != 1:
                raise ValueError(f"unknown policy setting {key!r}")
            data[owners[0]][key] = _plain(value)
        return Policy.model_validate(data)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal | int | float):
        number = Decimal(str(value)).normalize()
        return format(number, "f")
    return value


def _plain(value: Any) -> Any:
    """Floats become strings so Decimal settings stay exact."""
    if isinstance(value, float):
        return repr(value)
    return value


def _read_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"policy file {path} must hold a mapping")
    # YAML floats → strings, so money and percentages stay exact Decimals.
    return json.loads(json.dumps(data), parse_float=str)


def load_policy(path: Path | None = None) -> Policy:
    """Read the policy YAML (default `POLICY_PATH`)."""
    return Policy.model_validate(_read_yaml(path or get_settings().policy_path))


# --- saved overrides (PUT /policy) -------------------------------------------------------------


def overrides_path() -> Path:
    return get_settings().data_dir / "policy_overrides.json"


def saved_overrides() -> dict[str, Any]:
    path = overrides_path()
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    return data if isinstance(data, dict) else {}


def active_policy() -> Policy:
    """The policy runs are decided with: the YAML plus any overrides saved from the Policy page."""
    base = load_policy()
    saved = saved_overrides()
    return base.with_overrides(saved) if saved else base


def save_overrides(overrides: Mapping[str, Any]) -> Policy:
    """Validate and persist overrides (merged section by section over earlier ones)."""
    merged: dict[str, Any] = saved_overrides()
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    policy = load_policy().with_overrides(merged)
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, default=str, indent=2), encoding="utf-8")
    return policy
