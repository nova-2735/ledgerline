"""Eval harness smoke test: fake provider, three scenarios, report written and parsed."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.eval.__main__ import main
from app.eval.harness import FieldCheck, ScenarioResult, compare_fields, run_eval
from app.eval.report import field_tally, render


@pytest.fixture
def world(demo_world: Path) -> Path:
    from shutil import copytree

    from app.config import get_settings

    target = get_settings().data_dir / "demo"
    copytree(demo_world, target)
    return target


def test_fake_eval_three_scenarios(world: Path, tmp_path: Path) -> None:
    result = run_eval(only=["S01", "S04", "S06"])
    assert [r.doc_id for r in result.results] == ["S01", "S04", "S06"]
    assert result.correct == 3
    s04 = result.results[1]
    assert s04.after_review == [
        {"action": "confirm_po", "expected": "APPROVE", "actual": "APPROVE"}
    ]
    assert s04.render == "scanned" and s04.llm["provider"] == "fake"

    out = tmp_path / "eval_fake.md"
    out.write_text(render(result), encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    verdict = re.search(r"\*\*. (\d+) of (\d+) decisions correct\*\*", text)
    assert verdict is not None and verdict.groups() == ("3", "3")
    assert "invoice fields read correctly: " in text.splitlines()[2]
    rows = [ln for ln in text.splitlines() if ln.startswith("| S0")]
    assert len(rows) == 3 and all(ln.rstrip().endswith("| ✓ |") for ln in rows)
    assert "confirm_po → APPROVE" in rows[1]
    total_row = next(ln for ln in text.splitlines() if ln.startswith("| **All fields**"))
    assert total_row.count("(100.0%)") == 3
    assert json.dumps(result.to_json(), default=str)


def test_cli_writes_report_and_json(
    world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")  # main() sets it; restored after the test
    out = tmp_path / "r.md"
    assert main(["--provider", "fake", "--only", "S09", "--out", str(out), "--gate"]) == 0
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["correct"] == 1 and data["results"][0]["outcome"] == "RETURN"


def test_problem_and_field_tally() -> None:
    r = ScenarioResult(
        doc_id="S99",
        repeat=1,
        title="t",
        edge_case=None,
        render="scanned",
        expected_outcome="HOLD",
        expected_route="buyer",
        required=["PO_INFERRED"],
        allowed=[],
        outcome="HOLD",
        route="buyer",
        reasons=["FIELD_LOW_CONFIDENCE"],
        fields=[FieldCheck("total", "10", "10"), FieldCheck("total", "10", "11")],
    )
    assert r.problem == "missing PO_INFERRED"
    tally = field_tally([r])
    assert tally["total"]["scanned"] == (1, 2) and "digital" not in tally["total"]
    assert "✗ missing PO_INFERRED" in render_one(r)


def render_one(r: ScenarioResult) -> str:
    from app.eval.harness import EvalResult

    return render(EvalResult("fake", "m", "2026-11-20", False, "p", [r]))


def test_compare_fields_counts_missing_lines(world: Path) -> None:
    truth = json.loads((world / "truth" / "S01.json").read_text(encoding="utf-8"))
    checks = compare_fields(truth, None)
    lines = [c for c in checks if c.field.startswith("line ")]
    assert len(lines) == 6 and not any(c.ok for c in lines)


def test_fake_eval_stress_pack(world: Path) -> None:
    result = run_eval(only=["U05", "U09", "U10"], stress=True)
    assert result.pack == "stress"
    assert [r.doc_id for r in result.results] == ["U05", "U09", "U10"]
    assert result.correct == 3, [r.problem for r in result.results]
    u05 = result.results[0]
    assert u05.fields and all(f.ok for f in u05.fields)  # printed truth, same normalisation
    assert render(result).startswith("# Evaluation (stress pack)")
