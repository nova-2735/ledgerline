"""`python -m app.eval --provider fake|gemini [--only S04,S06] [--repeat 1] [--force-fresh]
[--out reports/eval_<provider>.md] [--gate]`

Runs in its own working directory (a temporary DATA_DIR and SQLite database), so the demo
database is never touched. Writes the Markdown scorecard and a `.json` next to it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from app.config import REPO_ROOT

DEMO_TODAY = "2026-11-20"  # the demo world's "today"


def _configure(provider: str, work: Path) -> None:
    os.environ["LLM_PROVIDER"] = provider
    os.environ["APP_ENV"] = "development"
    os.environ["APP_TODAY"] = DEMO_TODAY
    os.environ["DATA_DIR"] = str(work)
    os.environ["DATABASE_URL"] = f"sqlite:///{(work / 'ledgerline.db').as_posix()}"
    from app import db
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_caches()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval", description=__doc__)
    parser.add_argument("--provider", choices=("fake", "gemini"), default="fake")
    parser.add_argument("--only", help="comma-separated scenario ids, e.g. S04,S06")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--force-fresh", action="store_true", help="bypass the model cache")
    parser.add_argument("--out", type=Path, help="report path (default reports/eval_<provider>.md)")
    parser.add_argument("--gate", action="store_true", help="exit 1 unless every decision is right")
    args = parser.parse_args(argv)

    out = args.out or REPO_ROOT / "reports" / f"eval_{args.provider}.md"
    if not out.is_absolute():
        out = Path.cwd() / out
    only = [s.strip().upper() for s in args.only.split(",")] if args.only else None

    with tempfile.TemporaryDirectory(prefix="ledgerline-eval-") as tmp:
        _configure(args.provider, Path(tmp))
        from app.eval.harness import run_eval
        from app.eval.report import render

        result = run_eval(only=only, repeat=max(1, args.repeat), force_fresh=args.force_fresh)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(result), encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(result.to_json(), indent=2, default=str), encoding="utf-8"
    )
    total = len(result.results)
    print(f"{result.correct}/{total} decisions correct - report: {out.resolve()}")
    if args.gate and result.correct != total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
