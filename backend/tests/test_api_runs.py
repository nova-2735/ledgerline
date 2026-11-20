"""Runs API: upload, live events, listing, document and page images, audit, access code."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.enums import StageName
from tests.helpers.seeded import replay, wait_run


def _pdf(seeded: Path, doc_id: str) -> bytes:
    return (seeded / "demo" / "inbox" / f"{doc_id}.pdf").read_bytes()


def test_upload_s01_approves_and_replays_all_stages(api: TestClient, seeded_db: Path) -> None:
    resp = api.post(
        "/api/runs", files={"file": ("S01 invoice.pdf", _pdf(seeded_db, "S01"), "application/pdf")}
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    detail = wait_run(api, run_id)
    assert (detail["status"], detail["outcome"], detail["final_outcome"]) == (
        "completed",
        "APPROVE",
        "APPROVE",
    )
    assert detail["source"] == "upload" and detail["filename"] == "S01 invoice.pdf"
    assert detail["decision"]["posting"]["lines"][0]["gl_account"] == "510200"
    assert [s["name"] for s in detail["stages"]] == [s.value for s in StageName]
    assert all(s["status"] in ("passed", "warned") for s in detail["stages"])

    events = replay(api, run_id)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "run.created" and events[-1]["type"] == "run.completed"
    transitions = [(e["type"], e["stage"]) for e in events if e["type"].startswith("stage.")]
    transitions = [t for t in transitions if t[0] != "stage.log"]
    expected = [(t, s.value) for s in StageName for t in ("stage.started", "stage.completed")]
    assert transitions == expected
    done = {e["stage"]: e for e in events if e["type"] == "stage.completed"}
    assert done["intake"]["data"]["detail"]["pages"] == 1
    assert done["extract_fields"]["data"]["detail"]["provider"] == "fake"
    assert done["resolve_po"]["data"]["detail"]["method"] == "explicit"
    assert {c["rule_id"] for c in done["identify_vendor"]["data"]["checks"]} >= {"V01_resolve"}
    assert any(e["type"] == "decision.made" for e in events)
    # late join: replay after a cursor returns only the tail
    assert replay(api, run_id, after=len(events) - 1) == events[-1:]


def test_same_file_again_is_rejected_as_duplicate(api: TestClient, seeded_db: Path) -> None:
    first = api.post("/api/demo/runs/S01").json()["run_id"]
    wait_run(api, first)
    second = api.post("/api/demo/runs/S01").json()["run_id"]
    detail = wait_run(api, second)
    assert detail["outcome"] == "REJECT"
    assert detail["primary_reason"] == "DUPLICATE_SAME_FILE"


def test_list_filter_and_search(api: TestClient) -> None:
    body = api.get("/api/runs", params={"limit": 3}).json()
    assert body["total"] == 24 and len(body["items"]) == 3
    assert body["items"][0]["scenario_id"] == "H23"  # newest first
    held = api.get("/api/runs", params={"status": "awaiting_review"}).json()
    assert [r["scenario_id"] for r in held["items"]] == ["H23"]
    found = api.get("/api/runs", params={"q": "SPI/26-27/0198"}).json()
    assert {r["scenario_id"] for r in found["items"]} == {"H14", "H19"}
    rejected = api.get("/api/runs", params={"outcome": "REJECT"}).json()
    assert [r["scenario_id"] for r in rejected["items"]] == ["H19"]
    assert api.get("/api/runs/9999").status_code == 404


def test_document_page_and_audit(api: TestClient) -> None:
    run_id = api.get("/api/runs", params={"q": "H04"}).json()["items"][0]["id"]
    doc = api.get(f"/api/runs/{run_id}/document")
    assert doc.status_code == 200 and doc.content.startswith(b"%PDF")
    page = api.get(f"/api/runs/{run_id}/pages/1.png", params={"scale": 0.5})
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    assert api.get(f"/api/runs/{run_id}/pages/2.png").status_code == 404
    audit = api.get(f"/api/runs/{run_id}/audit").json()
    assert audit["run"]["id"] == run_id and audit["events"][0]["type"] == "run.created"
    assert audit["raw_model_output"]["invoice_number"] == "SPI/26-27/0121"


@pytest.mark.parametrize(
    ("content", "code"),
    [(b"hello, not a pdf", "not_pdf"), (b"%PDF-1.7\n garbage", "corrupt")],
)
def test_upload_rejects_bad_files(api: TestClient, content: bytes, code: str) -> None:
    resp = api.post("/api/runs", files={"file": ("x.pdf", content, "application/pdf")})
    assert resp.status_code == 422 and resp.json()["code"] == code


def test_access_code(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ACCESS_CODE", "letmein")
    get_settings.cache_clear()
    assert api.get("/api/health").status_code == 200
    assert api.get("/api/runs").status_code == 401
    assert api.get("/api/runs", headers={"X-Access-Code": "nope"}).status_code == 401
    assert api.get("/api/runs", headers={"X-Access-Code": "letmein"}).status_code == 200
    run_id = api.get("/api/runs", headers={"X-Access-Code": "letmein"}).json()["items"][0]["id"]
    assert api.get(f"/api/runs/{run_id}/document", params={"code": "letmein"}).status_code == 200
    assert api.get("/api/runs", params={"code": "letmein"}).status_code == 401
