from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.decide.policy import load_policy


def test_default_policy_matches_contract() -> None:
    p = load_policy()
    assert p.version == "2026-11-20.1"
    assert p.tolerances.unit_price_pct == Decimal("2.0")
    assert p.tolerances.header_abs == Decimal("2500.00")
    assert p.approval.auto_approve_limit == Decimal("500000.00")
    assert p.po_inference.min_score == 0.75 and not p.po_inference.auto_accept_inferred
    assert p.duplicates.window_days == 365
    assert p.extraction.min_confidence_critical == 0.80
    assert re.fullmatch(r"2026-11-20\.1\+[0-9a-f]{8}", p.policy_version)


def test_version_is_stable_and_changes_with_overrides() -> None:
    p = load_policy()
    assert load_policy().policy_version == p.policy_version
    q = p.with_overrides({"unit_price_pct": 10})
    assert q.tolerances.unit_price_pct == Decimal("10")
    assert q.policy_version != p.policy_version
    assert p.tolerances.unit_price_pct == Decimal("2.0")  # original untouched


def test_overrides_nested_and_flat_agree() -> None:
    p = load_policy()
    flat = p.with_overrides({"unit_price_pct": 10, "header_pct": 10, "header_abs": 5000})
    nested = p.with_overrides(
        {"tolerances": {"unit_price_pct": "10", "header_pct": 10.0, "header_abs": "5000.00"}}
    )
    assert flat.tolerances == nested.tolerances
    assert flat.tolerances.header_abs == Decimal("5000.00")
    assert flat.policy_version == nested.policy_version


@pytest.mark.parametrize(
    "bad",
    [{"nonsense": 1}, {"tolerances": {"nonsense": 1}}, {"tolerances": 5}, {"version": "x"}],
)
def test_unknown_override_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        load_policy().with_overrides(bad)


def test_policy_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = get_settings().policy_path.read_text("utf-8")
    custom = tmp_path / "policy.yaml"
    custom.write_text(src.replace('version: "2026-11-20.1"', 'version: "custom.1"'), "utf-8")
    monkeypatch.setenv("POLICY_PATH", str(custom))
    get_settings.cache_clear()
    assert load_policy().version == "custom.1"
