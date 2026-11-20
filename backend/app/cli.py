"""Command-line tools: `python -m app.cli <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import BACKEND_DIR, LLMProvider, get_settings

DEFAULT_OPENAPI_PATH = BACKEND_DIR / "openapi.json"


def export_openapi(out: Path) -> Path:
    from app.main import create_app

    schema = create_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("utf-8"))
    return out


def list_models() -> int:
    from app.llm.base import LLMError
    from app.llm.gemini import GeminiClient

    settings = get_settings()
    try:
        names = GeminiClient(settings).list_models()
    except LLMError as exc:
        print(f"Could not list models: {exc}", file=sys.stderr)
        return 1
    for name in names:
        print(name)
    configured = (("LLM_MODEL", settings.llm_model), ("LLM_MODEL_LIGHT", settings.llm_model_light))
    for label, model in configured:
        state = "available" if model in names else "NOT in the list for this key"
        print(f"{label}={model}: {state}")
    return 0


def _cell(value: object, width: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def extract_file(pdf: Path, fresh: bool, raw_out: Path | None) -> int:
    from app import db
    from app.extract.extractor import extract
    from app.ingest.reader import IntakeError, read_bytes
    from app.llm.base import LLMError, get_client
    from app.models.extraction import FieldValue

    settings = get_settings()
    db.init_db()
    data = pdf.read_bytes()
    try:
        doc = read_bytes(data)
        result = extract(data, doc, get_client(settings), force_fresh=fresh)
    except IntakeError as exc:
        print(f"Can't read {pdf.name}: {exc.message}", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"Model call failed: {exc}", file=sys.stderr)
        return 1
    ex = result.extraction
    print(f"{pdf.name}: {doc.doc_kind.value}, {doc.page_count} page(s), {ex.doc_type.value}")
    for event in result.events:
        print(f"  - {event.message}")
    print()
    print(f"{'field':<22} {'printed':<34} {'value':<22} {'grounded':<11} conf  level")
    for name in type(ex).model_fields:
        fv = getattr(ex, name)
        if not isinstance(fv, FieldValue):
            continue
        print(
            f"{name:<22} {_cell(fv.raw, 34):<34} {_cell(fv.value, 22):<22} "
            f"{fv.grounded:<11} {fv.confidence:4.2f}  {fv.level.value}"
        )
    print()
    print(f"{'#':<3} {'description':<44} {'qty':>8} {'rate':>12} {'amount':>12} {'tax%':>5}")
    for ln in ex.line_items:
        print(
            f"{ln.index:<3} {_cell(ln.description, 44):<44} {_cell(ln.quantity, 8):>8} "
            f"{_cell(ln.unit_price, 12):>12} {_cell(ln.amount, 12):>12} "
            f"{_cell(ln.tax_rate_pct, 5):>5}"
        )
    t = ex.tax
    print(
        f"\ntax: {t.kind} cgst={t.cgst} sgst={t.sgst} igst={t.igst} total={t.total_tax} "
        f"rates={[str(r) for r in t.rates_pct]}"
    )
    print(
        f"po canonical: {ex.po_reference_canonical}  "
        f"invoice canonical: {ex.invoice_number_canonical}"
    )
    if ex.annotations:
        print("annotations:", "; ".join(ex.annotations))
    if raw_out is not None:
        raw_out.write_text(ex.meta.raw.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"raw transcription written to {raw_out}")
    if settings.llm_provider is LLMProvider.fake:
        print("(provider: fake — values come from the generator's ground truth)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_openapi = sub.add_parser("export-openapi", help="write the OpenAPI schema as JSON")
    p_openapi.add_argument("--out", type=Path, default=DEFAULT_OPENAPI_PATH)

    sub.add_parser("models", help="list Gemini models this API key can call")
    p_extract = sub.add_parser("extract", help="read one PDF and print the extracted fields")
    p_extract.add_argument("pdf", type=Path)
    p_extract.add_argument("--fresh", action="store_true", help="ignore the cache")
    p_extract.add_argument("--raw-out", type=Path, default=None, help="save the raw transcription")

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.command == "models":
        return list_models()
    if args.command == "extract":
        return extract_file(args.pdf, args.fresh, args.raw_out)
    if args.command == "export-openapi":
        path = export_openapi(args.out)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
