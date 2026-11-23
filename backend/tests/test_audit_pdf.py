"""Audit PDF export: opens, carries the run id, outcome, checks and timeline; needs the code."""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.helpers.seeded import wait_run


def _pdf_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert doc.page_count >= 2
        return "\n".join(page.get_text() for page in doc)


def test_audit_pdf_for_a_held_run(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/S06").json()["run_id"])
    resp = api.get(f"/api/runs/{run['id']}/audit.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert f"{run['display_id']}-audit.pdf" in resp.headers["content-disposition"]
    text = _pdf_text(resp.content)
    assert run["display_id"] in text and "HOLD" in text
    for heading in (
        "Next step",
        "Checks (",
        "Extracted fields",
        "Stage timeline",
        "Review actions",
    ):
        assert heading in text, heading
    assert "VLI/26-27/0311" in text and "BANK_DETAILS_CHANGED" in text
    assert "Policy version" in text and run["policy_version"] in text


def test_audit_pdf_after_review_lists_the_action_and_both_decisions(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/S06").json()["run_id"])
    api.post(
        f"/api/runs/{run['id']}/review",
        json={"action": "verify_bank", "reviewer": "Treasury desk", "note": "Called back on file"},
    )
    run = wait_run(api, run["id"])
    text = _pdf_text(api.get(f"/api/runs/{run['id']}/audit.pdf").content)
    assert "Treasury desk" in text and "Called back on file" in text
    assert "APPROVE" in text and "Decision history" in text


def test_audit_pdf_for_a_foreign_currency_run_writes_usd(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U05").json()["run_id"])
    text = _pdf_text(api.get(f"/api/runs/{run['id']}/audit.pdf").content)
    assert "USD 5,212.50" in text


def test_audit_pdf_unknown_run_is_404(api: TestClient) -> None:
    assert api.get("/api/runs/99999/audit.pdf").status_code == 404


def test_audit_pdf_respects_the_access_code(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = wait_run(api, api.post("/api/demo/runs/S01").json()["run_id"])
    monkeypatch.setenv("DEMO_ACCESS_CODE", "letmein")
    get_settings.cache_clear()
    url = f"/api/runs/{run['id']}/audit.pdf"
    assert api.get(url).status_code == 401
    assert api.get(url, headers={"X-Access-Code": "letmein"}).status_code == 200
    assert api.get(url, params={"code": "letmein"}).status_code == 200  # download link
    assert api.get(url, params={"code": "wrong"}).status_code == 401
