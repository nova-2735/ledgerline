"""Robustness pack: the ten unseen stress documents (U01–U10) and the fixes they drove."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.demo.seed import load_manifest, world_dir
from app.demo.unseen import STRESS
from app.enums import CheckStatus, StageStatus
from app.extract.invoice_refs import invoices_in_file, printed_numbers, referenced_invoices
from app.extract.normalize import currency_code, currency_in, parse_amount
from app.ingest.ocr import tesseract_path
from app.ingest.reader import read_bytes
from app.rules.base import inr, money_currency
from tests.helpers.seeded import wait_run

STRESS_IDS = [s.doc_id for s in STRESS]


def _pdf(world: Path, doc_id: str) -> bytes:
    return (world / load_manifest(world)["documents"][doc_id]["file"]).read_bytes()


def _truth(world: Path, doc_id: str) -> dict[str, Any]:
    truth: dict[str, Any] = json.loads(
        (world / "truth" / f"{doc_id}.json").read_text(encoding="utf-8")
    )
    return truth


# --- the generated pack ---------------------------------------------------------------------------


def test_pack_has_ten_documents_with_truth(demo_world: Path) -> None:
    docs = load_manifest(demo_world)["documents"]
    stress = sorted(k for k, v in docs.items() if v["kind"] == "stress")
    assert stress == STRESS_IDS
    index = json.loads((demo_world / "truth" / "index.json").read_text(encoding="utf-8"))
    for doc_id in stress:
        assert (demo_world / "unseen" / f"{doc_id}.pdf").is_file()
        assert index[docs[doc_id]["sha256"]] == doc_id
        assert _truth(demo_world, doc_id)["expected"]["outcome"] in {"HOLD", "RETURN", "REJECT"}


def test_layout_properties(demo_world: Path) -> None:
    with pymupdf.open(stream=_pdf(demo_world, "U01"), filetype="pdf") as doc:
        assert doc.page_count == 2
        assert "Grand Total" not in doc[0].get_text() and "Grand Total" in doc[1].get_text()
    assert len(_truth(demo_world, "U01")["raw"]["line_items"]) == 28
    with pymupdf.open(stream=_pdf(demo_world, "U02"), filetype="pdf") as doc:
        page = doc[0]
        assert page.rect.width > page.rect.height and not page.get_text().strip()
    with pymupdf.open(stream=_pdf(demo_world, "U09"), filetype="pdf") as doc:
        assert doc.page_count == 2


# --- end to end, offline (ground-truth reader) ---------------------------------------------------


@pytest.mark.parametrize("doc_id", STRESS_IDS)
def test_stress_document_gets_a_sensible_decision(api: TestClient, doc_id: str) -> None:
    world = world_dir()
    exp = _truth(world, doc_id)["expected"]
    resp = api.post(f"/api/demo/runs/{doc_id}")
    assert resp.status_code == 202, resp.text
    run = wait_run(api, resp.json()["run_id"])
    assert run["status"] != "failed", run["stages"]
    decision = run["decision"]
    assert (decision["outcome"], decision["route"]) == (exp["outcome"], exp["route"])
    failing = {c["code"] for c in run["checks"] if c["status"] == "fail"}
    assert set(exp["required"]) <= failing
    assert failing <= set(exp["required"]) | set(exp["allowed"]) | set(exp["live_also"])
    handoff = decision["handoff"]
    assert handoff and handoff["question"] and handoff["suggested_action"]
    assert "{" not in handoff["question"] + handoff["suggested_action"]


def test_inbox_lists_stress_documents_as_their_own_group(api: TestClient) -> None:
    items = {i["doc_id"]: i for i in api.get("/api/demo/inbox").json()}
    assert items["S01"]["group"] == "scenario"
    assert items["U09"]["group"] == "stress" and "stress" in items["U09"]["tags"]
    assert api.post("/api/demo/runs/U99").status_code == 404
    assert api.post("/api/demo/runs/X01").status_code == 422


# --- the fixes ------------------------------------------------------------------------------------


def test_two_invoices_in_one_file_stop_the_pipeline(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U09").json()["run_id"])
    assert run["extraction"]["invoices_in_file"] == ["RSE/0466", "RSE/0467"]
    stages = {s["name"]: s["status"] for s in run["stages"]}
    for name in ("identify_vendor", "check_tax", "resolve_po", "match_lines", "check_duplicates"):
        assert stages[name] == StageStatus.skipped.value
    assert "RSE/0466 and RSE/0467" in run["decision"]["handoff"]["question"]


def test_invoice_number_detection_on_the_pack(demo_world: Path) -> None:
    def numbers(doc_id: str) -> Any:
        return printed_numbers(read_bytes(_pdf(demo_world, doc_id), ocr=False))

    assert invoices_in_file(numbers("U01")) == []  # page 2 repeats its own number
    assert invoices_in_file(numbers("U09")) == ["RSE/0466", "RSE/0467"]
    assert referenced_invoices(numbers("U06")) == ["SPI/26-27/0198"]
    assert invoices_in_file(numbers("U07")) == []  # the e-way bill number is not an invoice
    for doc_id in ("S01", "S06", "S12"):
        assert invoices_in_file(numbers(doc_id)) == []


def test_credit_note_is_linked_to_its_invoice_and_skips_po_matching(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U06").json()["run_id"])
    stages = {s["name"]: s for s in run["stages"]}
    assert stages["resolve_po"]["status"] == stages["match_lines"]["status"] == "skipped"
    assert stages["identify_vendor"]["status"] == "passed"
    question = run["decision"]["handoff"]["question"]
    assert "SPI/26-27/0198" in question and "approved" in question and "₹1,817.00" in question


def test_unregistered_supplier_is_not_returned_for_a_gstin(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U04").json()["run_id"])
    tax = {c["rule_id"]: c for c in run["checks"] if c["stage"] == "check_tax"}
    assert tax["T01_supplier_gstin"]["status"] == CheckStatus.skip.value
    assert tax["T02_buyer_gstin"]["status"] == CheckStatus.skip.value
    assert "isn't GST-registered" in tax["T01_supplier_gstin"]["message"]


def test_foreign_currency_is_read_flagged_and_shown_in_its_currency(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U05").json()["run_id"])
    ex = run["extraction"]
    assert ex["currency"] == "USD" and ex["total"]["value"] == "5212.50"
    assert ex["bank_account_number"]["level"] == "high"  # no IFSC needed for a foreign bank
    currency = next(c for c in run["checks"] if c["code"] == "CURRENCY_MISMATCH")
    assert "USD" in currency["title"]
    texts = json.dumps(run["decision"])
    assert "USD 5,212.50" in texts and "₹5,212.50" not in texts


def test_non_invoice_skips_field_checks(api: TestClient) -> None:
    run = wait_run(api, api.post("/api/demo/runs/U10").json()["run_id"])
    failing = [c["code"] for c in run["checks"] if c["status"] == "fail"]
    assert failing == ["DOC_NOT_INVOICE"]
    assert "delivery challan" in run["decision"]["handoff"]["question"]


@pytest.mark.parametrize(
    ("text", "amount", "currency"),
    [
        ("USD 5,212.50", "5212.50", "USD"),
        ("$5,212.50", "5212.50", "USD"),
        ("Rs. 1,16,348/-", "116348.00", "INR"),
        ("€ 980.00", "980.00", "EUR"),
        ("-1,925.00", "-1925.00", None),
    ],
)
def test_foreign_amounts_parse(text: str, amount: str, currency: str | None) -> None:
    assert str(parse_amount(text)) == amount
    assert currency_in(text) == currency


def test_currency_codes() -> None:
    assert [currency_code(x) for x in ("US$", "usd", "Rs.", None, "₹", "GBP")] == [
        "USD", "USD", "INR", "INR", "INR", "GBP",
    ]  # fmt: skip


def test_money_follows_the_run_currency_and_does_not_leak() -> None:
    from decimal import Decimal

    assert inr(Decimal("116348")) == "₹1,16,348.00"
    with money_currency("USD"):
        assert inr(Decimal("5212.5")) == "USD 5,212.50"
    assert inr(Decimal("5212.5")) == "₹5,212.50"


@pytest.mark.ocr
@pytest.mark.skipif(tesseract_path() is None, reason="Tesseract not installed")
def test_sideways_scan_is_turned_upright_for_ocr(demo_world: Path) -> None:
    doc = read_bytes(_pdf(demo_world, "U02"), ocr=True)
    page = doc.pages[0]
    texts = [w.text for w in page.words]
    assert "Apex" in texts and "AIS/26-27/1241" in texts
    word = next(w for w in page.words if w.text == "AIS/26-27/1241")
    # the text runs bottom to top on the landscape page: its box is tall and narrow
    assert (word.bbox.y1 - word.bbox.y0) > (word.bbox.x1 - word.bbox.x0)


@pytest.mark.parametrize(
    ("title", "payable"),
    [
        ("BILL", True),
        ("Cash Bill", True),
        ("Bill of Supply", True),
        ("Invoice", True),
        ("DELIVERY CHALLAN", False),
        ("e-Way Bill", False),
        ("Payment Receipt", False),
        (None, True),  # no heading, but a bill number and a total
    ],
)
def test_a_bill_the_model_filed_as_other_is_checked_as_an_invoice(
    title: str | None, payable: bool
) -> None:
    from app.rules.document import d01_doc_type
    from tests.rules.builders import make_ctx, make_extraction

    ctx = make_ctx(make_extraction(document_type="other", document_title=title))
    [result] = d01_doc_type(ctx)
    if payable:
        assert result.status == CheckStatus.pass_ and "asking for payment" in result.message
    else:
        assert result.code is not None and result.code.value == "DOC_NOT_INVOICE"


def test_an_unlabelled_document_without_a_bill_number_is_not_an_invoice() -> None:
    from app.rules.document import d01_doc_type
    from tests.rules.builders import make_ctx, make_extraction

    ex = make_extraction(document_type="other", document_title=None, invoice_number=None)
    [result] = d01_doc_type(make_ctx(ex))
    assert result.code is not None and result.code.value == "DOC_NOT_INVOICE"
