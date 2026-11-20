from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import reset_caches

TEST_TODAY = "2026-11-20"


@pytest.fixture(autouse=True)
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_TODAY", TEST_TODAY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    reset_caches()
    yield tmp_path
    reset_caches()
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
