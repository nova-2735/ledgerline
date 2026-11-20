from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.enums import CheckStatus, ReasonCode
from app.models.checks import CheckResult
from app.models.common import Model, Money
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction, RawInvoice
from app.models.run import RunDetail, RunEvent

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"

# Copied by hand from plan RULES §2 so a drift in either place fails this test.
RULES_REASON_CODES = """
DOC_NOT_INVOICE DOC_PROFORMA DOC_CREDIT_NOTE DOC_UNREADABLE
FIELD_MISSING_INVOICE_NUMBER FIELD_MISSING_INVOICE_DATE FIELD_MISSING_TOTAL FIELD_MISSING_SUPPLIER
FIELD_LOW_CONFIDENCE MATH_LINE_MISMATCH MATH_SUBTOTAL_MISMATCH MATH_TOTAL_MISMATCH
ROUND_OFF_APPLIED TAX_INCLUSIVE_NORMALIZED TOTAL_WORDS_MISMATCH DATE_IN_FUTURE DATE_STALE
VENDOR_NOT_FOUND VENDOR_BLOCKED VENDOR_GSTIN_MISMATCH VENDOR_MATCHED_BY_NAME BANK_DETAILS_CHANGED
SENDER_DOMAIN_MISMATCH
GSTIN_INVALID BUYER_GSTIN_MISMATCH TAX_TYPE_MISMATCH TAX_AMOUNT_MISMATCH TAX_RATE_MISMATCH
PO_NOT_FOUND PO_INFERRED PO_AMBIGUOUS PO_MISSING PO_VENDOR_MISMATCH PO_CLOSED CURRENCY_MISMATCH
DATE_BEFORE_PO
LINE_NOT_ON_PO MISC_CHARGE_ALLOWED LINES_BUNDLED PRICE_VARIANCE_WITHIN_TOL PRICE_VARIANCE_OVER_TOL
PRICE_BELOW_PO AMOUNT_VARIANCE_OVER_TOL QTY_EXCEEDS_PO_REMAINING QTY_EXCEEDS_RECEIVED
GOODS_NOT_RECEIVED
DUPLICATE_SAME_FILE DUPLICATE_SAME_INVOICE DUPLICATE_SUSPECTED
APPROVAL_LIMIT_EXCEEDED
""".split()

CONTRACT_PATHS = {
    ("get", "/api/health"),
    ("post", "/api/runs"),
    ("post", "/api/demo/runs/{doc_id}"),
    ("get", "/api/demo/inbox"),
    ("post", "/api/demo/reset"),
    ("get", "/api/runs"),
    ("get", "/api/runs/{run_id}"),
    ("get", "/api/runs/{run_id}/events"),
    ("get", "/api/runs/{run_id}/document"),
    ("get", "/api/runs/{run_id}/pages/{n}.png"),
    ("get", "/api/runs/{run_id}/audit"),
    ("post", "/api/runs/{run_id}/review"),
    ("get", "/api/queue"),
    ("get", "/api/vendors"),
    ("get", "/api/purchase-orders"),
    ("get", "/api/purchase-orders/{po}"),
    ("get", "/api/policy"),
    ("post", "/api/policy/preview"),
    ("put", "/api/policy"),
    ("get", "/api/stats"),
}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture", "model"),
    [
        ("raw_invoice", RawInvoice),
        ("invoice_extraction", InvoiceExtraction),
        ("check_result", CheckResult),
        ("decision", Decision),
        ("run_detail", RunDetail),
        ("run_event", RunEvent),
    ],
)
def test_fixture_round_trips(fixture: str, model: type[BaseModel]) -> None:
    data = load(fixture)
    assert model.model_validate(data).model_dump(mode="json") == data


def test_fixture_specifics() -> None:
    check = CheckResult.model_validate(load("check_result"))
    assert check.code is ReasonCode.BANK_DETAILS_CHANGED
    decision = Decision.model_validate(load("decision"))
    assert decision.outcome == "HOLD"
    assert decision.handoff is not None
    event = RunEvent.model_validate(load("run_event"))
    assert event.type == "stage.completed"


def test_reason_codes_equal_rules_list() -> None:
    assert len(RULES_REASON_CODES) == len(set(RULES_REASON_CODES))
    members = {c.value for c in ReasonCode}
    assert members == set(RULES_REASON_CODES)
    assert all(c.name == c.value for c in ReasonCode)


class _Amount(Model):
    amount: Money


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("116348", "116348.00"),
        ("116348.005", "116348.01"),
        ("0.125", "0.13"),
        ("-2.345", "-2.35"),
        (Decimal("116348"), "116348.00"),
        (116348, "116348.00"),
    ],
)
def test_money_serialises_as_two_dp_string(given: object, expected: str) -> None:
    dumped = _Amount.model_validate({"amount": given}).model_dump(mode="json")
    assert dumped == {"amount": expected}
    assert isinstance(_Amount.model_validate({"amount": given}).amount, Decimal)


@pytest.mark.parametrize("bad", [116348.0, True, "1,16,348.00", "NaN", "Infinity", None])
def test_money_rejects_floats_and_non_numbers(bad: object) -> None:
    with pytest.raises(ValidationError):
        _Amount.model_validate({"amount": bad})


def test_money_in_check_result_json() -> None:
    data = load("check_result")
    data["amount_at_risk"] = "116348"
    assert CheckResult.model_validate(data).model_dump(mode="json")["amount_at_risk"] == (
        "116348.00"
    )


@pytest.mark.parametrize("field", ["total", "subtotal", "round_off"])
def test_raw_invoice_rejects_float_money(field: str) -> None:
    data = load("raw_invoice")
    data[field] = 116348.0
    with pytest.raises(ValidationError):
        RawInvoice.model_validate(data)


def test_raw_invoice_rejects_float_line_amount() -> None:
    data = load("raw_invoice")
    data["line_items"][0]["amount"] = 77000.0
    with pytest.raises(ValidationError):
        RawInvoice.model_validate(data)


def test_raw_invoice_forbids_extra_keys() -> None:
    data = load("raw_invoice")
    data["confidence"] = "high"
    with pytest.raises(ValidationError):
        RawInvoice.model_validate(data)
    data = load("raw_invoice")
    data["tax_lines"][0]["note"] = "x"
    with pytest.raises(ValidationError):
        RawInvoice.model_validate(data)


def test_failing_check_requires_code() -> None:
    data = load("check_result")
    data["code"] = None
    with pytest.raises(ValidationError):
        CheckResult.model_validate(data)
    data["status"] = CheckStatus.pass_.value
    assert CheckResult.model_validate(data).code is None


def test_naive_datetimes_are_taken_as_utc() -> None:
    data = load("run_event")
    data["ts"] = "2026-11-20T05:12:29.412000"
    assert RunEvent.model_validate(data).model_dump(mode="json")["ts"] == (
        "2026-11-20T05:12:29.412000Z"
    )


def test_openapi_contains_every_contract_path(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    present = {(method, path) for path, ops in schema["paths"].items() for method in ops}
    assert present >= CONTRACT_PATHS


def test_openapi_money_is_string(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    amount = schemas["CheckResult"]["properties"]["amount_at_risk"]
    assert {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["116348.00"]} in amount[
        "anyOf"
    ]


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/runs", {}),
        ("get", "/api/runs/1", {}),
        ("get", "/api/runs/1/document", {}),
        ("get", "/api/runs/1/pages/1.png", {}),
        ("get", "/api/runs/1/audit", {}),
        ("post", "/api/runs", {"files": {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}}),
        ("post", "/api/demo/runs/S01", {"json": {"force_fresh": False}}),
        ("get", "/api/demo/inbox", {}),
        ("post", "/api/demo/reset", {}),
        (
            "post",
            "/api/runs/1/review",
            {"json": {"action": "approve", "reviewer": "a", "note": "ok"}},
        ),
        ("get", "/api/queue", {}),
        ("get", "/api/vendors", {}),
        ("get", "/api/purchase-orders", {}),
        ("get", "/api/purchase-orders/KF-PO-0142", {}),
        ("get", "/api/policy", {}),
        ("post", "/api/policy/preview", {"json": {"overrides": {}}}),
        ("put", "/api/policy", {"json": {"overrides": {}}}),
        ("get", "/api/stats", {}),
    ],
)
def test_stub_endpoints_return_501(
    client: TestClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    resp = client.request(method, path, **kwargs)
    assert resp.status_code == 501
    assert resp.json() == {"detail": "not implemented", "code": "not_implemented"}


def test_sse_stub_is_event_stream(client: TestClient) -> None:
    resp = client.get("/api/runs/1/events")
    assert resp.status_code == 501
    assert resp.headers["content-type"].startswith("text/event-stream")


def test_validation_errors_use_error_shape(client: TestClient) -> None:
    resp = client.post("/api/runs/1/review", json={"action": "nope"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], str)


def test_init_db_creates_contract_tables(client: TestClient) -> None:
    from sqlalchemy import inspect

    from app.db import get_engine

    tables = set(inspect(get_engine()).get_table_names())
    assert {
        "company",
        "vendors",
        "purchase_orders",
        "po_lines",
        "goods_receipts",
        "documents",
        "runs",
        "run_events",
        "review_actions",
        "invoice_ledger",
        "llm_cache",
    } <= tables


def test_orm_money_and_sqlite_pragmas(client: TestClient) -> None:
    from datetime import date

    from sqlalchemy import text

    from app.db import get_engine, get_sessionmaker
    from app.orm import POLineRow, PurchaseOrderRow, VendorRow

    with get_sessionmaker()() as session:
        session.add(
            VendorRow(
                vendor_id="V001",
                legal_name="Sharma Packaging Industries",
                aliases=[],
                gstin="27AAKFS2231P1ZS",
                pan="AAKFS2231P",
                state_code="27",
                address="Pune",
                city="Pune",
                email="accounts@sharmapackaging.example",
                phone_on_file="+91 20 2712 4455",
                bank_name="HDFC Bank",
                bank_account_number="50200012345678",
                bank_ifsc="HDFC0000123",
                status="active",
                block_reason=None,
                payment_terms_days=30,
                category="packaging",
            )
        )
        po = PurchaseOrderRow(
            po_number="KF-PO-0142",
            vendor_id="V001",
            po_date=date(2026, 10, 28),
            status="open",
            currency="INR",
            match_type="three_way",
            buyer_name="Vikram Shetty",
            cost_center="BLR-PLANT-01",
        )
        po.lines.append(
            POLineRow(
                line_no=1,
                item_code="PKG-CB-0450",
                description="Corrugated shipper box",
                quantity=Decimal("2000"),
                uom="Nos",
                unit_price=Decimal("38.5"),
                tax_rate_pct=Decimal("18"),
                hsn_sac="4819",
                gl_account="510200",
            )
        )
        session.add(po)
        session.commit()

    with get_sessionmaker()() as session:
        line = session.query(POLineRow).one()
        assert line.unit_price == Decimal("38.50") and str(line.unit_price) == "38.50"
        assert line.quantity == Decimal("2000")
        raw = session.execute(text("SELECT unit_price FROM po_lines")).scalar_one()
        assert raw == 3850

    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
