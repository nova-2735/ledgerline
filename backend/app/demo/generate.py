"""Generate the demo world: reference data, inbox and history PDFs, ground truth and manifest.

python -m app.demo.generate --out data/demo
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.clock import IST
from app.config import get_settings

from .invoice import (
    DocSpec,
    World,
    build_printed,
    compute,
    expected_values,
    load_specs,
    load_world,
    raw_invoice,
)
from .scanify import scanify
from .templates import get_template
from .templates.base import rupee_available, rupee_font
from .unseen import generate_unseen

SEED = 42
OUTPUT_DIRS = ("reference", "inbox", "history", "truth", "unseen")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline=""
    )


def write_reference(world: World, out: Path) -> None:
    ref = out / "reference"
    _write_json(ref / "company.json", world.company.model_dump(mode="json"))
    _write_csv(
        ref / "vendors.csv",
        "vendor_id,legal_name,aliases,gstin,pan,state_code,address,city,email,phone_on_file,"
        "bank_name,bank_account_number,bank_ifsc,status,block_reason,payment_terms_days,category".split(","),
        [
            [
                v.vendor_id, v.legal_name, ";".join(v.aliases), v.gstin, v.pan, v.state_code,
                v.address, v.city, v.email, v.phone_on_file, v.bank_name, v.bank_account_number,
                v.bank_ifsc, v.status, v.block_reason or "", v.payment_terms_days, v.category,
            ]
            for v in world.vendors.values()
        ],
    )  # fmt: skip
    _write_csv(
        ref / "purchase_orders.csv",
        "po_number,vendor_id,po_date,status,currency,match_type,buyer_name,cost_center,line_no,"
        "item_code,description,quantity,uom,unit_price,tax_rate_pct,hsn_sac,gl_account".split(","),
        [
            [
                po.po_number, po.vendor_id, po.po_date.isoformat(), po.status, po.currency,
                po.match_type.value, po.buyer_name, po.cost_center, ln.line_no, ln.item_code,
                ln.description, str(ln.quantity), ln.uom, f"{ln.unit_price:.2f}",
                str(ln.tax_rate_pct), ln.hsn_sac, ln.gl_account,
            ]
            for po in sorted(world.purchase_orders.values(), key=lambda p: p.po_number)
            for ln in po.lines
        ],
    )  # fmt: skip
    _write_csv(
        ref / "goods_receipts.csv",
        ["grn_number", "po_number", "line_no", "quantity_received", "received_date"],
        [
            [
                g.grn_number,
                g.po_number,
                g.line_no,
                str(g.quantity_received),
                g.received_date.isoformat(),
            ]
            for g in world.goods_receipts
        ],
    )


def render_document(spec: DocSpec, world: World, rupee_ok: bool) -> tuple[bytes, dict[str, Any]]:
    """PDF bytes and the truth record for one document."""
    if rupee_ok and rupee_font() is None:
        raise RuntimeError("rupee_ok requested but no font with the ₹ glyph is available")
    template = get_template(spec.style.template)
    figures = compute(spec)
    printed = build_printed(spec, figures, world, template.caps, rupee_ok)
    pdf = template.render(printed)
    if spec.render == "scanned":
        if spec.scan is None:
            raise ValueError(f"{spec.id}: render=scanned needs a scan block")
        pdf = scanify(pdf, spec.scan, spec.index, title=f"Scan {spec.id}")
    truth = {
        "doc_id": spec.id,
        "kind": spec.kind,
        "render": spec.render,
        "template": spec.style.template,
        "raw": raw_invoice(spec, printed).model_dump(mode="json"),
        "expected_values": expected_values(spec, figures),
        "expected": spec.meta.get("expected"),
    }
    return pdf, truth


def _at(day: date, minutes_after_ten: int) -> datetime:
    return datetime.combine(day, time(10, 0), IST) + timedelta(minutes=minutes_after_ten)


def history_timeline(specs: list[DocSpec]) -> dict[str, dict[str, Any]]:
    """Deterministic processed/received/review timestamps for the history (random.Random(42))."""
    rng = random.Random(SEED)
    timeline: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if spec.kind != "history":
            continue
        processed = _at(spec.meta["processed"], rng.randrange(0, 7 * 60 + 1))
        received = processed - timedelta(minutes=rng.randint(15, 180))
        entry: dict[str, Any] = {"processed_at": processed, "received_at": received}
        for key in ("review", "review_if_raised"):
            review = spec.meta.get(key)
            if not review:
                continue
            day = review["date"]
            if day == processed.date():
                at = processed + timedelta(minutes=rng.randint(20, 120))
            else:
                at = _at(day, rng.randrange(0, 7 * 60 + 1))
            entry[key] = {k: v for k, v in review.items() if k != "date"} | {"at": at}
        timeline[spec.id] = entry
    return timeline


def _iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value


def _email(spec: DocSpec, timeline: dict[str, Any]) -> dict[str, Any]:
    if "email" in spec.meta:
        return dict(spec.meta["email"])
    subject = (
        f"Invoice {spec.number}" if spec.number else f"Invoice from {spec.supplier.legal_name}"
    )
    return {
        "sender_name": spec.supplier.legal_name,
        "sender_email": spec.supplier.email,
        "subject": subject,
        "received_at": timeline["received_at"],
    }


def generate(out: Path) -> dict[str, Any]:
    """Write the demo world under `out` and return the manifest."""
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_DIRS:
        shutil.rmtree(out / name, ignore_errors=True)
        (out / name).mkdir()
    world = load_world()
    specs = load_specs(world)
    rupee_ok = rupee_available()
    write_reference(world, out)
    timeline = history_timeline(specs)

    pdfs: dict[str, bytes] = {}
    index: dict[str, str] = {}
    documents: dict[str, Any] = {}
    for spec in sorted(specs, key=lambda s: (s.kind != "inbox", s.id, s.copy_of is not None)):
        if spec.copy_of:
            continue
        pdf, truth = render_document(spec, world, rupee_ok)
        pdfs[spec.id] = pdf
        _write_json(out / "truth" / f"{spec.id}.json", _iso(truth))
    for spec in specs:
        if spec.copy_of:
            pdfs[spec.id] = pdfs[spec.copy_of]
            truth = json.loads((out / "truth" / f"{spec.copy_of}.json").read_text(encoding="utf-8"))
            truth.update(doc_id=spec.id, copy_of=spec.copy_of, expected=spec.meta.get("expected"))
            _write_json(out / "truth" / f"{spec.id}.json", truth)

    for spec in sorted(specs, key=lambda s: (s.kind != "inbox", s.id)):
        folder = "inbox" if spec.kind == "inbox" else "history"
        rel = f"{folder}/{spec.id}.pdf"
        (out / rel).write_bytes(pdfs[spec.id])
        sha = _sha256(pdfs[spec.id])
        index.setdefault(sha, spec.id)
        tl = timeline.get(spec.id, {})
        documents[spec.id] = _iso(
            {
                "file": rel,
                "sha256": sha,
                "kind": spec.kind,
                "title": spec.meta.get("title"),
                "edge_case": spec.meta.get("edge_case"),
                "tags": spec.meta.get("tags", []),
                "vendor_id": spec.supplier.vendor_id,
                "template": spec.style.template,
                "render": spec.render,
                "copy_of": spec.copy_of,
                "email": _email(spec, tl),
                "processed_at": tl.get("processed_at"),
                "review": tl.get("review"),
                "review_if_raised": tl.get("review_if_raised"),
                "awaiting_review": bool(spec.meta.get("awaiting_review", False)),
                "expected": spec.meta.get("expected"),
            }
        )
    documents.update(generate_unseen(out, index))
    _write_json(out / "truth" / "index.json", index)
    manifest = {
        "seed": SEED,
        "today": "2026-11-20",
        "currency_mark_rupee_glyph": rupee_ok,
        "history_order": [s.id for s in specs if s.kind == "history"],
        "documents": documents,
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic demo world.")
    parser.add_argument(
        "--out", type=Path, default=None, help="output directory (default DATA_DIR/demo)"
    )
    args = parser.parse_args(argv)
    out = args.out or get_settings().data_dir / "demo"
    manifest = generate(out)
    docs = manifest["documents"]
    kinds = [d["kind"] for d in docs.values()]
    print(
        f"Wrote {kinds.count('inbox')} inbox, {kinds.count('history')} history and "
        f"{kinds.count('stress')} stress documents to {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
