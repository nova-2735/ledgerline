"""Seed the demo database: reference data plus the processed history (SCENARIOS §6).

History documents go through the real pipeline with the offline (fake) reader and a backdated
clock, in the order they were processed; the listed reviewer actions are then applied at their
recorded times. Seeded runs have `source=seed`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, select

from app import clock, db
from app.config import get_settings
from app.decide.policy import overrides_path
from app.demo import snapshot
from app.demo.generate import generate
from app.enums import ActionType, RunSource, RunStatus
from app.llm.fake import FakeClient
from app.models.api import ReviewRequest
from app.orm import Base, RunRow
from app.pipeline import runner
from app.pipeline.review import apply_review
from app.reference.loader import load_reference

KEEP_TABLES = frozenset({"llm_cache"})  # saved model readings survive a reset
RESET_WAIT_S = 60.0  # how long a reset waits for in-flight runs and reviews
log = logging.getLogger(__name__)


def world_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / "demo"


def load_manifest(world: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((world / "manifest.json").read_text(encoding="utf-8"))
    return manifest


def reset_database() -> None:
    """Drop and recreate every table except the model cache; forget saved policy overrides."""
    engine = db.get_engine()
    tables = [t for t in Base.metadata.sorted_tables if t.name not in KEEP_TABLES]
    Base.metadata.drop_all(engine, tables=tables)
    Base.metadata.create_all(engine)
    overrides_path().unlink(missing_ok=True)


def history_order(manifest: dict[str, Any]) -> list[str]:
    """By processed date, ties in table order (SCENARIOS §6)."""
    order: list[str] = manifest["history_order"]
    docs = manifest["documents"]
    return sorted(order, key=lambda i: (docs[i]["processed_at"][:10], order.index(i)))


def _review_request(review: dict[str, Any]) -> ReviewRequest:
    return ReviewRequest(
        action=ActionType(review["action"]),
        reviewer=review["reviewer"],
        note=review.get("note") or "Reviewed",
        po_number=review.get("po_number"),
        field_corrections=review.get("field_corrections"),
        fields_verified=review.get("fields_verified"),
    )


def seed(
    data_dir: Path | None = None, *, regenerate: bool = False, wait_s: float | None = None
) -> int:
    """Rebuild the demo database through the pipeline. Returns the number of runs created.

    New uploads and reviews are refused while this runs; in-flight work gets `wait_s` seconds to
    finish (default `RESET_WAIT_S`), else `runner.ResetTimeout` is raised and nothing is touched."""
    world = world_dir(data_dir)
    with runner.exclusive(RESET_WAIT_S if wait_s is None else wait_s):
        if regenerate or not (world / "manifest.json").is_file():
            generate(world)
        return _reseed_and_save(world)


@dataclass(frozen=True)
class ResetResult:
    runs: int
    mode: Literal["snapshot", "reseed"]
    duration_ms: int


def reset(wait_s: float | None = None) -> ResetResult:
    """Put the demo back to its seeded state: restore the seeded snapshot when there is a current
    one (seconds), else reseed through the pipeline (a minute or more). Same locking as `seed`."""
    start = time.perf_counter()
    settings = get_settings()
    world = world_dir()
    with runner.exclusive(RESET_WAIT_S if wait_s is None else wait_s):
        source = snapshot.find_snapshot(settings)
        mode: Literal["snapshot", "reseed"] = "reseed"
        if source is not None:
            try:
                snapshot.restore(settings, source)
                overrides_path().unlink(missing_ok=True)
                mode = "snapshot"
            except sqlite3.Error:
                log.exception("restoring the seeded snapshot failed; reseeding instead")
        if mode == "reseed":
            if not (world / "manifest.json").is_file():
                generate(world)
            runs = _reseed_and_save(world)
        else:
            runs = _count_runs()
    return ResetResult(runs, mode, int((time.perf_counter() - start) * 1000))


def _reseed_and_save(world: Path) -> int:
    runs = _reseed(world)
    snapshot.save_local(get_settings(), runs)
    return runs


def _count_runs() -> int:
    with db.get_sessionmaker()() as session:
        return int(session.scalar(select(func.count()).select_from(RunRow)) or 0)


def _reseed(world: Path) -> int:
    manifest = load_manifest(world)
    reset_database()
    with db.get_sessionmaker()() as session:
        load_reference(session, world)

    client = FakeClient(get_settings(), truth_dir=world / "truth")
    docs = manifest["documents"]
    for doc_id in history_order(manifest):
        info = docs[doc_id]
        email = info.get("email") or {}
        with clock.backdated(datetime.fromisoformat(info["processed_at"])):
            run_id = runner.submit(
                (world / info["file"]).read_bytes(),
                f"{doc_id}.pdf",
                runner.SubmitMeta(
                    source=RunSource.seed,
                    scenario_id=doc_id,
                    sender_name=email.get("sender_name"),
                    sender_email=email.get("sender_email"),
                    subject=email.get("subject"),
                ),
                background=False,
                client=client,
                polish=False,
            )
        review = info.get("review")
        if review is None and info.get("review_if_raised") and _awaiting(run_id):
            review = info["review_if_raised"]
        if review is not None and _awaiting(run_id):
            with clock.backdated(datetime.fromisoformat(review["at"])):
                apply_review(
                    run_id, _review_request(review), background=False, client=client, polish=False
                )

    return _count_runs()


def _awaiting(run_id: int) -> bool:
    with db.get_sessionmaker()() as session:
        run = session.get(RunRow, run_id)
        return run is not None and run.status == RunStatus.awaiting_review.value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the demo database with history.")
    parser.add_argument("--regenerate", action="store_true", help="regenerate the demo world")
    args = parser.parse_args(argv)
    db.init_db()
    try:
        count = seed(regenerate=args.regenerate)
    except (runner.ResetInProgress, runner.ResetTimeout) as exc:
        print(f"Not seeded: {exc}")
        return 1
    print(f"Seeded {count} runs into {get_settings().resolved_database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
