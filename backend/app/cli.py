"""Command-line tools: `python -m app.cli <command>`."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.config import BACKEND_DIR

DEFAULT_OPENAPI_PATH = BACKEND_DIR / "openapi.json"


def export_openapi(out: Path) -> Path:
    from app.main import create_app

    schema = create_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("utf-8"))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_openapi = sub.add_parser("export-openapi", help="write the OpenAPI schema as JSON")
    p_openapi.add_argument("--out", type=Path, default=DEFAULT_OPENAPI_PATH)

    args = parser.parse_args(argv)
    if args.command == "export-openapi":
        path = export_openapi(args.out)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
