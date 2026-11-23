"""Dashboard stats, reference views, demo and policy endpoints on the seeded database."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.routes_stats import run_exposure
from app.orm import RunRow
from tests.helpers.seeded import wait_run


def test_stats_on_seeded_history(api: TestClient) -> None:
    body = api.get("/api/stats", params={"days": 90}).json()
    k = body["kpis"]
    assert k["processed"] == 24
    assert k["awaiting_review"] == 1
    assert k["median_decision_ms"] is None  # seeded runs are left out of timing
    assert Decimal(k["value_processed"]) > 0
    # 19 of 24 auto-approved (18 if H13 needed a field check)
    assert k["touchless_rate"] in (round(19 / 24, 4), round(18 / 24, 4))
    # only H19 (duplicate, 36,344) carries an exposure code among non-approved runs
    assert Decimal(k["exposure_stopped"]) == Decimal("36344.00")
    assert len(body["by_day"]) == 90
    assert sum(d["REJECT"] for d in body["by_day"]) == 1
    reasons = {r["code"]: r for r in body["by_reason"]}
    assert reasons["DUPLICATE_SAME_FILE"]["count"] == 1
    routes = {r["route"]: r["count"] for r in body["by_route"]}
    assert routes["receiving"] == 1 and routes["controller"] == 1


def test_stats_window_and_live_timing(api: TestClient) -> None:
    short = api.get("/api/stats", params={"days": 1}).json()
    assert short["kpis"]["processed"] == 0 and len(short["by_day"]) == 1
    run_id = api.post("/api/demo/runs/S01").json()["run_id"]
    wait_run(api, run_id)
    k = api.get("/api/stats", params={"days": 1}).json()["kpis"]
    assert k["processed"] == 1 and k["median_decision_ms"] is not None


def test_run_exposure_takes_largest_failing_exposure_check() -> None:
    def check(code: str, status: str, amount: str | None) -> dict[str, object]:
        return {"code": code, "status": status, "amount_at_risk": amount}

    run = RunRow(
        checks=[
            check("QTY_EXCEEDS_PO_REMAINING", "fail", "17110.00"),
            check("QTY_EXCEEDS_RECEIVED", "fail", "34220.00"),
            check("PRICE_VARIANCE_WITHIN_TOL", "warn", "999999.00"),
            check("GOODS_NOT_RECEIVED", "fail", "50000.00"),
        ]
    )
    assert run_exposure(run) == Decimal("34220.00")


def test_vendors_and_purchase_orders(api: TestClient) -> None:
    vendors = api.get("/api/vendors").json()
    v001 = next(v for v in vendors if v["vendor_id"] == "V001")
    assert v001["bank_account_number"].startswith("****")
    assert v001["invoice_count"] >= 5 and v001["open_po_count"] >= 1
    pos = {p["po_number"]: p for p in api.get("/api/purchase-orders").json()}
    assert Decimal(pos["KF-PO-0126"]["pct_billed"]) == Decimal("100.00")
    detail = api.get("/api/purchase-orders/KF-PO-0119").json()
    assert Decimal(detail["balances"][0]["billed"]) == 60
    assert len(detail["grns"]) == 3
    assert [r["scenario_id"] for r in detail["runs"]] == ["H01", "H02"]
    only = api.get("/api/purchase-orders", params={"vendor_id": "V003"}).json()
    assert {p["vendor_id"] for p in only} == {"V003"}
    assert api.get("/api/purchase-orders/NOPE").status_code == 404


def test_demo_inbox(api: TestClient) -> None:
    inbox = api.get("/api/demo/inbox").json()
    groups = [i["group"] for i in inbox]
    assert (groups.count("scenario"), groups.count("stress")) == (15, 10)
    s04 = next(i for i in inbox if i["doc_id"] == "S04")
    assert s04["is_edge_case"] and s04["subject"] == "bill" and s04["processed_run_ids"] == []
    run_id = api.post("/api/demo/runs/S04").json()["run_id"]
    wait_run(api, run_id)
    s04 = next(i for i in api.get("/api/demo/inbox").json() if i["doc_id"] == "S04")
    assert s04["processed_run_ids"] == [run_id]
    assert api.post("/api/demo/runs/S99").status_code == 404


def test_demo_reset_reseeds(api: TestClient) -> None:
    run_id = api.post("/api/demo/runs/S01").json()["run_id"]
    wait_run(api, run_id)
    assert api.get("/api/runs").json()["total"] == 25
    body = api.post("/api/demo/reset").json()
    assert (body["status"], body["runs"], body["mode"]) == ("ok", 24, "snapshot")
    assert api.get("/api/runs").json()["total"] == 24


def test_policy_preview_and_update(api: TestClient) -> None:
    run_id = api.post("/api/demo/runs/S12").json()["run_id"]
    wait_run(api, run_id)
    policy = api.get("/api/policy").json()
    assert policy["version"] and policy["policy"]["tolerances"]
    preview = api.post(
        "/api/policy/preview",
        json={"overrides": {"unit_price_pct": 10, "header_pct": 10, "header_abs": 5000}},
    ).json()
    changed = {c["run_id"]: c for c in preview["changed"]}
    assert changed[run_id]["before"] == "HOLD" and changed[run_id]["after"] == "APPROVE"
    assert preview["unchanged"] >= 20
    assert api.get(f"/api/runs/{run_id}").json()["outcome"] == "HOLD"  # nothing persisted
    bad = api.post("/api/policy/preview", json={"overrides": {"nope": 1}})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_policy")

    saved = api.put("/api/policy", json={"overrides": {"tolerances": {"unit_price_pct": 3}}})
    assert saved.status_code == 200 and saved.json()["version"] != policy["version"]
    assert Decimal(api.get("/api/policy").json()["policy"]["tolerances"]["unit_price_pct"]) == 3
