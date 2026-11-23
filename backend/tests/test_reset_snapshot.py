"""Demo reset restores the seeded snapshot (seconds) and reseeds only without a current one."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.decide.policy import overrides_path
from app.demo import snapshot
from app.orm import LLMCacheRow, RunRow
from tests.helpers.seeded import wait_run

SEEDED_RUNS = 24


def _runs() -> int:
    with get_sessionmaker()() as s:
        return int(s.scalar(select(func.count()).select_from(RunRow)) or 0)


def _add_cache_row(key: str) -> None:
    with get_sessionmaker()() as s:
        s.add(
            LLMCacheRow(
                key=key,
                kind="extract",
                provider="gemini",
                model="live-model",
                prompt_version="1",
                response={"raw": {}, "meta": {}},
                created_at=datetime.now(UTC),
            )
        )
        s.commit()


def _cache_keys() -> set[str]:
    with get_sessionmaker()() as s:
        return set(s.scalars(select(LLMCacheRow.key)))


def test_reset_restores_the_snapshot_and_keeps_saved_readings(api: TestClient) -> None:
    run_id = api.post("/api/demo/runs/S01").json()["run_id"]
    wait_run(api, run_id)
    _add_cache_row("live-reading")
    overrides_path().write_text('{"tolerances": {"header_pct": 9}}', encoding="utf-8")
    assert _runs() == SEEDED_RUNS + 1

    body = api.post("/api/demo/reset").json()

    assert (body["status"], body["mode"], body["runs"]) == ("ok", "snapshot", SEEDED_RUNS)
    assert body["duration_ms"] < 5000
    assert _runs() == SEEDED_RUNS
    assert api.get(f"/api/runs/{run_id}").status_code == 404
    assert "live-reading" in _cache_keys()
    assert not overrides_path().exists()
    # the restored database is fully usable: a new run gets the next id and decides
    again = api.post("/api/demo/runs/S01").json()["run_id"]
    assert wait_run(api, again)["outcome"] == "APPROVE"


def test_a_broken_snapshot_falls_back_to_reseeding_and_is_rewritten(api: TestClient) -> None:
    local = snapshot.local_dir(get_settings())
    (local / snapshot.DB_FILE).write_bytes(b"not a database")

    body = api.post("/api/demo/reset").json()

    assert (body["mode"], body["runs"]) == ("reseed", SEEDED_RUNS)
    assert snapshot.find_snapshot(get_settings()) == local
    assert api.post("/api/demo/reset").json()["mode"] == "snapshot"


def test_a_stale_snapshot_is_ignored(seeded_db: Path) -> None:
    settings = get_settings()
    local = snapshot.local_dir(settings)
    assert snapshot.find_snapshot(settings) == local
    meta = json.loads((local / snapshot.META_FILE).read_text(encoding="utf-8"))
    meta["fingerprint"] = "older-code"
    (local / snapshot.META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    assert snapshot.find_snapshot(settings) is None


def test_the_build_time_snapshot_wins_and_is_never_overwritten(
    seeded_db: Path, tmp_path: Path
) -> None:
    settings = get_settings()
    image = tmp_path / "seed-data"
    image.mkdir()
    shutil.copyfile(snapshot.local_dir(settings) / snapshot.DB_FILE, image / snapshot.DB_FILE)
    assert snapshot.find_snapshot(settings, built_in=image) == image
    # seeding the image's snapshot directory itself doesn't write a second copy inside it
    assert snapshot.save_local(settings, SEEDED_RUNS, built_in=settings.data_dir) is None


def test_no_snapshot_for_external_databases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/ledgerline")
    get_settings.cache_clear()
    assert snapshot.find_snapshot(get_settings()) is None
