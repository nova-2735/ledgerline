"""Every inbox scenario end to end on a fresh seeded database (SCENARIOS §5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.helpers.seeded import wait_run
from tests.helpers.world import expectations

pytestmark = pytest.mark.scenarios
INBOX = [f"S{i:02d}" for i in range(1, 16)]


def _check_outcome(run: dict[str, Any], exp: dict[str, Any]) -> None:
    d = run["decision"]
    assert (d["outcome"], d["route"]) == (exp["outcome"], exp["route"]), d["reasons"]
    assert set(exp["required"]) <= set(d["reasons"]), d["reasons"]
    allowed = set(exp["required"]) | set(exp.get("allowed", []))
    assert set(d["reasons"]) <= allowed, d["reasons"]
    if "primary" in exp:
        assert d["primary_reason"] == exp["primary"]
    assert run["status"] == ("completed" if d["final"] else "awaiting_review")


@pytest.mark.parametrize("doc_id", INBOX)
def test_scenario_end_to_end(api: TestClient, seeded_db: Path, doc_id: str) -> None:
    exp = expectations()[doc_id]
    run_id = api.post(f"/api/demo/runs/{doc_id}").json()["run_id"]
    run = wait_run(api, run_id)
    assert run["source"] == "demo" and run["scenario_id"] == doc_id
    _check_outcome(run, exp)
    for step in exp.get("after_review", []):
        body = {
            "action": step["action"],
            "reviewer": step.get("reviewer", "Priya Nair (AP)"),
            "note": step.get("note", "Checked"),
        }
        for key in ("po_number", "fields_verified", "field_corrections"):
            if key in step:
                body[key] = step[key]
        resp = api.post(f"/api/runs/{run_id}/review", json=body)
        assert resp.status_code == 200, resp.text
        run = wait_run(api, run_id)
        assert run["decision"]["outcome"] == step["outcome"], run["decision"]["reasons"]
        if "note_contains" in step:
            text = " ".join(run["decision"]["notes"]) + run["decision"]["explanation"]["summary"]
            assert step["note_contains"] in text


def test_queue_counts_by_route(api: TestClient) -> None:
    for doc_id in INBOX:
        wait_run(api, api.post(f"/api/demo/runs/{doc_id}").json()["run_id"])
    queue = api.get("/api/queue").json()
    held = [d for d in INBOX if expectations()[d]["outcome"] in ("HOLD", "RETURN")]
    want: dict[str, int] = {"receiving": 1}  # H23 from the history
    for d in held:
        route = expectations()[d]["route"]
        want[route] = want.get(route, 0) + 1
    assert queue["counts"] == want
    k = api.get("/api/stats").json()["kpis"]
    assert k["processed"] > 0 and k["awaiting_review"] == len(held) + 1
    assert float(k["value_processed"]) > 0 and float(k["exposure_stopped"]) > 0
    assert k["median_decision_ms"] is not None and k["touchless_rate"] > 0
