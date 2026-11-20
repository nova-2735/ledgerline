"""A seeded demo database built once per test session and copied into each test's DATA_DIR."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.pipeline import runner

TEST_TODAY = "2026-11-20"


@contextmanager
def temp_env(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    get_settings.cache_clear()
    db.reset_caches()
    try:
        yield
    finally:
        runner.shutdown()
        db.reset_caches()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


def build_template(out: Path, demo_world: Path) -> Path:
    """Generate (copy) the world and seed a database under `out` (a DATA_DIR)."""
    from app.demo.seed import seed

    shutil.copytree(demo_world, out / "demo")
    with temp_env(APP_ENV="test", APP_TODAY=TEST_TODAY, DATA_DIR=str(out)):
        db.init_db()
        seed()
    return out


def install(template: Path) -> Path:
    """Copy a seeded DATA_DIR into the current test's DATA_DIR."""
    target = get_settings().data_dir
    db.reset_caches()
    shutil.copytree(template, target, dirs_exist_ok=True)
    return target


@pytest.fixture(scope="session")
def seed_template(tmp_path_factory: pytest.TempPathFactory, demo_world: Path) -> Path:
    return build_template(tmp_path_factory.mktemp("seed_template") / "data", demo_world)


@pytest.fixture
def seeded_db(seed_template: Path) -> Iterator[Path]:
    target = install(seed_template)
    yield target
    runner.wait_idle()


@pytest.fixture
def api(seeded_db: Path) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def wait_run(client: TestClient, run_id: int, timeout: float = 60) -> dict[str, Any]:
    """Wait for the run to stop executing and return its detail."""
    deadline = time.monotonic() + timeout
    while True:
        runner.wait_idle(timeout=timeout)
        detail: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] not in ("queued", "running") or time.monotonic() > deadline:
            return detail
        time.sleep(0.05)


def replay(client: TestClient, run_id: int, after: int = 0) -> list[dict[str, Any]]:
    """Read the SSE stream until it closes; returns the events."""
    import json

    events = []
    with client.stream("GET", f"/api/runs/{run_id}/events", params={"after": after}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events
