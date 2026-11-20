"""Test world: generate the demo world, load the reference data and seed the PO ledger.

Seeding here is a stand-in for the real history seed: every history document whose expected final
outcome is APPROVE gets a document, a completed run and an `invoice_ledger` row that bills the
PO lines it was written against.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app import db
from app.demo.generate import generate
from app.demo.invoice import DocSpec, compute, load_specs, load_world
from app.enums import DocKind, Outcome, RunSource, RunStatus
from app.extract.extractor import normalise
from app.extract.normalize import canonical_invoice_number, parse_date
from app.models.extraction import DocumentRead, ExtractionMeta, InvoiceExtraction, RawInvoice
from app.orm import DocumentRow, RunRow
from app.reference.ledger import BilledLine, Ledger, LedgerEntry
from app.reference.loader import load_reference


@dataclass
class SeededWorld:
    root: Path
    session: Session
    counts: dict[str, int]
    run_ids: dict[str, int]  # history doc id → run id

    def extraction(self, doc_id: str) -> InvoiceExtraction:
        return extraction_from_truth(self.root, doc_id)


def final_outcome(spec: DocSpec) -> Outcome | None:
    """Expected outcome after any seeded review (None while awaiting review)."""
    if spec.meta.get("awaiting_review"):
        return None
    review = spec.meta.get("review")
    if review:
        action = review["action"]
        if action == "approve":
            return Outcome.APPROVE
        if action == "send_to_vendor":
            return Outcome.RETURN
        if action == "reject":
            return Outcome.REJECT
    return Outcome(spec.meta["expected"]["outcome"])


def extraction_from_truth(root: Path, doc_id: str) -> InvoiceExtraction:
    """Normalise the ground-truth transcription (no PDF read, so grounding is unavailable)."""
    truth: dict[str, Any] = json.loads((root / "truth" / f"{doc_id}.json").read_text("utf-8"))
    raw = RawInvoice.model_validate(truth["raw"])
    doc = DocumentRead(
        sha256="0" * 64, pages=[], doc_kind=DocKind.digital, ocr_available=False, page_count=1
    )
    meta = ExtractionMeta(
        provider="fake",
        model="fake",
        prompt_id="extract_invoice",
        prompt_version="v1",
        latency_ms=0,
        input_tokens=None,
        output_tokens=None,
        cached=False,
        cached_at=None,
        raw=raw,
    )
    return normalise(raw, meta, doc)


def seed_history_ledger(session: Session, root: Path) -> dict[str, int]:
    """Insert runs + ledger rows for history items whose final outcome is APPROVE."""
    world = load_world()
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    ledger = Ledger(session)
    run_ids: dict[str, int] = {}
    for spec in load_specs(world):
        if spec.kind != "history" or final_outcome(spec) != Outcome.APPROVE:
            continue
        info = manifest["documents"][spec.id]
        pdf = (root / info["file"]).read_bytes()
        processed = datetime.fromisoformat(info["processed_at"]).astimezone(UTC)
        document = DocumentRow(
            sha256=hashlib.sha256(pdf).hexdigest(),
            filename=f"{spec.id}.pdf",
            bytes=pdf,
            page_count=1,
            created_at=processed,
        )
        session.add(document)
        session.flush()
        figures = compute(spec)
        parsed = parse_date(spec.date_text)
        run = RunRow(
            display_id=f"SEED-{spec.id}",
            document_id=document.id,
            source=RunSource.seed.value,
            scenario_id=spec.id,
            status=RunStatus.completed.value,
            created_at=processed,
            finished_at=processed,
            vendor_id=spec.supplier.vendor_id,
            po_number=spec.po_number,
            invoice_number=spec.number,
            invoice_number_canonical=canonical_invoice_number(spec.number),
            invoice_date=parsed.value if parsed else None,
            total=figures.total,
            outcome=Outcome(spec.meta["expected"]["outcome"]).value,
            final_outcome=Outcome.APPROVE.value,
        )
        session.add(run)
        session.flush()
        billed = [
            BilledLine(po_line_no=ln.po_line, qty=ln.qty, amount=fig.taxable)
            for ln, fig in zip(spec.lines, figures.lines, strict=True)
            if ln.po_line is not None
        ]
        ledger.upsert_entry(
            LedgerEntry(
                run_id=run.id,
                vendor_id=run.vendor_id,
                invoice_number=run.invoice_number,
                invoice_number_canonical=run.invoice_number_canonical,
                invoice_date=run.invoice_date,
                total=run.total,
                po_number=run.po_number,
                file_sha256=document.sha256,
                final_outcome=Outcome.APPROVE,
                billed_lines=billed,
            )
        )
        run_ids[spec.id] = run.id
    session.commit()
    return run_ids


@pytest.fixture(scope="session")
def demo_world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The generated demo world (PDFs, truth, reference CSVs), shared by the whole session."""
    out = tmp_path_factory.mktemp("demo_world")
    generate(out)
    return out


@pytest.fixture
def seeded_world(demo_world: Path) -> Iterator[SeededWorld]:
    """Fresh database with the reference data loaded and approved history in the ledger."""
    db.init_db()
    with db.get_sessionmaker()() as session:
        counts = load_reference(session, demo_world)
        run_ids = seed_history_ledger(session, demo_world)
        yield SeededWorld(demo_world, session, counts, run_ids)
