"""Review actions: finalise, or override and resume; the review queue."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers.seeded import replay, wait_run

PRIYA = "Priya Nair (AP)"


def _demo(api: TestClient, doc_id: str) -> dict[str, Any]:
    run_id = api.post(f"/api/demo/runs/{doc_id}").json()["run_id"]
    return wait_run(api, run_id)


def _review(api: TestClient, run_id: int, **body: Any) -> Any:
    return api.post(f"/api/runs/{run_id}/review", json={"reviewer": PRIYA, **body})


def test_s04_confirm_po_resumes_to_approve(api: TestClient) -> None:
    run = _demo(api, "S04")
    assert (run["outcome"], run["route"], run["status"]) == ("HOLD", "ap_clerk", "awaiting_review")
    resolve = next(s for s in run["stages"] if s["name"] == "resolve_po")
    assert resolve["detail"]["method"] == "inferred"
    assert resolve["detail"]["candidates"][0]["po_number"] == "KF-PO-0151"
    before = replay(api, run["id"])

    resp = _review(
        api,
        run["id"],
        action="confirm_po",
        po_number="KF-PO-0151",
        fields_verified=True,
        note="Matches GRN-0951 for the copper wire and MCBs",
    )
    assert resp.status_code == 200
    after = wait_run(api, run["id"])
    assert (after["outcome"], after["final_outcome"], after["status"]) == (
        "APPROVE",
        "APPROVE",
        "completed",
    )
    assert after["decision"]["version"] == 2 and len(after["decision_history"]) == 2
    assert after["review_actions"][0]["resulting_decision_version"] == 2
    assert after["po_number"] == "KF-PO-0151"
    stage = next(s for s in after["stages"] if s["name"] == "resolve_po")
    assert stage["detail"]["method"] == "confirmed"

    tail = replay(api, run["id"], after=before[-1]["seq"])
    types = [e["type"] for e in tail]
    assert types[:2] == ["review.recorded", "run.resumed"]
    assert tail[1]["data"]["from_stage"] == "resolve_po"
    restarted = [e["stage"] for e in tail if e["type"] == "stage.started"]
    assert restarted == [
        "resolve_po",
        "match_lines",
        "check_duplicates",
        "decide",
        "explain_route",
    ]
    assert types[-1] == "run.completed"


def test_s06_approve_blocked_until_bank_verified(api: TestClient) -> None:
    run = _demo(api, "S06")
    assert (run["outcome"], run["route"], run["primary_reason"]) == (
        "HOLD",
        "treasury",
        "BANK_DETAILS_CHANGED",
    )
    blocked = _review(api, run["id"], action="approve", note="Looks fine")
    assert blocked.status_code == 409 and blocked.json()["code"] == "critical_unresolved"

    ok = _review(
        api,
        run["id"],
        action="verify_bank",
        reviewer="Treasury",
        note="Called +91 79 2658 3300, spoke to accounts team",
    )
    assert ok.status_code == 200
    after = wait_run(api, run["id"])
    assert (after["outcome"], after["decision"]["version"]) == ("APPROVE", 2)
    remit = after["decision"]["posting"]["remit_to"]
    assert remit["bank_name"] == "HDFC Bank" and remit["ifsc"].startswith("HDFC")
    bank = next(c for c in after["checks"] if c["rule_id"] == "V04_bank_details")
    assert bank["resolved_by_review"] and "Resolved by Treasury" in bank["message"]
    vendor_stage = next(s for s in after["stages"] if s["name"] == "identify_vendor")
    assert vendor_stage["status"] == "warned"
    notes = " ".join(after["decision"]["notes"])
    assert "update vendor master via change control before the payment run" in notes


def test_final_actions(api: TestClient) -> None:
    s12 = _demo(api, "S12")
    resp = _review(api, s12["id"], action="approve", note="Buyer agreed the revised price")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["final_outcome"], body["status"]) == ("APPROVE", "completed")
    assert body["decision"]["headline"] == f"Approved by {PRIYA}"
    assert body["decision"]["posting"] is not None
    assert all(c["resolved_by_review"] for c in body["checks"] if c["status"] == "fail")
    po = api.get("/api/purchase-orders/KF-PO-0150").json()
    assert sum(float(b["billed"]) for b in po["balances"]) == 60
    again = _review(api, s12["id"], action="reject", note="Changed my mind")
    assert again.status_code == 409

    s09 = _demo(api, "S09")
    sent = _review(api, s09["id"], action="send_to_vendor", note="Emailed the draft")
    assert sent.json()["final_outcome"] == "RETURN"
    assert sent.json()["decision"]["explanation"]["vendor_message"] is not None


def test_validation_errors(api: TestClient) -> None:
    run = _demo(api, "S04")
    rid = run["id"]
    assert _review(api, rid, action="confirm_po", note="x").json()["code"] == "po_required"
    assert _review(api, rid, action="approve", note=" ").json()["code"] == "note_required"
    missing = _review(api, rid, action="confirm_po", po_number="KF-PO-9999", note="x")
    assert (missing.status_code, missing.json()["code"]) == (422, "po_not_found")
    bad = _review(api, rid, action="correct_fields", field_corrections={"colour": "red"}, note="x")
    assert bad.json()["code"] == "unknown_field"
    assert _review(api, 9999, action="approve", note="x").status_code == 404


def test_correct_fields_resumes_from_validation(api: TestClient) -> None:
    run = _demo(api, "S10")
    assert run["primary_reason"] == "FIELD_MISSING_INVOICE_NUMBER"
    resp = _review(
        api,
        run["id"],
        action="correct_fields",
        field_corrections={"invoice_number": "DCC/1131/26"},
        note="Vendor confirmed the number by phone",
    )
    assert resp.status_code == 200
    after = wait_run(api, run["id"])
    assert after["invoice_number"] == "DCC/1131/26"
    assert after["outcome"] == "APPROVE"
    assert after["extraction"]["invoice_number"]["level"] == "high"
    assert after["extraction"]["meta"]["raw"]["invoice_number"] is None  # model output kept


def test_not_duplicate_reopens_auto_reject(api: TestClient) -> None:
    run = _demo(api, "S05")
    assert (run["outcome"], run["status"]) == ("REJECT", "completed")
    resp = _review(api, run["id"], action="not_duplicate", note="Checked: different delivery")
    assert resp.status_code == 200
    after = wait_run(api, run["id"])
    assert "DUPLICATE_SAME_INVOICE" not in [
        c["code"] for c in after["checks"] if c["status"] == "fail" and not c["resolved_by_review"]
    ]
    assert after["decision"]["version"] == 2


def test_queue(api: TestClient) -> None:
    _demo(api, "S03")
    _demo(api, "S06")
    q = api.get("/api/queue").json()
    assert q["counts"] == {"receiving": 1, "buyer": 1, "treasury": 1}
    s03 = next(i for i in q["items"] if i["scenario_id"] == "S03")
    assert s03["amount_at_risk"] == "34220.00" and s03["question"]
    assert s03["age_hours"] >= 0
    only = api.get("/api/queue", params={"route": "treasury"}).json()
    assert [i["scenario_id"] for i in only["items"]] == ["S06"]
