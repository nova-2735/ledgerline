"""`RunDetail.approval_block` states, from the review endpoint's own guard, why approve is refused.

Regression: the run view offered an enabled Approve for S11 (vendor not in the master) because
the UI only knew about critical checks; the API then refused the click with a 409."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.helpers.seeded import wait_run


def _demo(api: TestClient, doc_id: str) -> dict[str, Any]:
    run_id = api.post(f"/api/demo/runs/{doc_id}").json()["run_id"]
    return wait_run(api, run_id)


def _approve(api: TestClient, run_id: int) -> Any:
    body = {"action": "approve", "reviewer": "Priya Nair (AP)", "note": "Looks fine"}
    return api.post(f"/api/runs/{run_id}/review", json=body)


@pytest.mark.parametrize(
    ("doc_id", "code", "phrase"),
    [
        ("S11", "posting_incomplete", "isn't in the vendor master"),
        ("S06", "critical_unresolved", "Bank details"),
        ("S10", "field_missing", "Can't approve"),
    ],
)
def test_approval_block_matches_the_refusal(
    api: TestClient, doc_id: str, code: str, phrase: str
) -> None:
    run = _demo(api, doc_id)
    assert run["approval_block"] and phrase.lower() in run["approval_block"].lower()
    refused = _approve(api, run["id"])
    assert (refused.status_code, refused.json()["code"]) == (409, code)
    assert refused.json()["detail"] == run["approval_block"]


def test_unknown_vendor_block_explains_onboarding(api: TestClient) -> None:
    block = _demo(api, "S11")["approval_block"]
    assert block.lower().startswith("can't approve: om sai traders isn't in the vendor master")
    assert "onboard" in block and "Correct the fields" not in block


def test_clean_invoice_has_no_approval_block(api: TestClient) -> None:
    run = _demo(api, "S01")
    assert run["outcome"] == "APPROVE" and run["approval_block"] is None


def test_bank_verification_lifts_the_block(api: TestClient) -> None:
    run = _demo(api, "S06")
    assert run["approval_block"]
    body = {
        "action": "verify_bank",
        "reviewer": "Treasury",
        "note": "Called +91 79 2658 3300, spoke to accounts team",
    }
    assert api.post(f"/api/runs/{run['id']}/review", json=body).status_code == 200
    assert wait_run(api, run["id"])["approval_block"] is None
