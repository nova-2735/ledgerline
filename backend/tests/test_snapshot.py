"""Fresh-container start: the build-time seeded snapshot is copied into an empty DATA_DIR."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.demo.snapshot import DB_FILE, restore_if_missing


def _snapshot(root: Path) -> Path:
    snap = root / "seed-data"
    (snap / "demo").mkdir(parents=True)
    (snap / DB_FILE).write_bytes(b"seeded")
    (snap / "demo" / "manifest.json").write_text("{}", encoding="utf-8")
    return snap


def test_restores_into_an_empty_data_dir(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    settings = get_settings()
    assert not (settings.data_dir / DB_FILE).exists()
    assert restore_if_missing(settings, snap) is True
    assert (settings.data_dir / DB_FILE).read_bytes() == b"seeded"
    assert (settings.data_dir / "demo" / "manifest.json").is_file()


def test_keeps_an_existing_database(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / DB_FILE).write_bytes(b"live")
    assert restore_if_missing(settings, snap) is False
    assert (settings.data_dir / DB_FILE).read_bytes() == b"live"


def test_no_snapshot_or_external_database_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    assert restore_if_missing(settings, tmp_path / "missing") is False
    snap = _snapshot(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/ledgerline")
    get_settings.cache_clear()
    assert restore_if_missing(get_settings(), snap) is False
    assert not (get_settings().data_dir / DB_FILE).exists()


def test_startup_line_names_provider_model_and_ocr() -> None:
    from app.main import startup_line

    line = startup_line(restored=True)
    assert "provider fake" in line and "OCR " in line and "restored the seeded demo data" in line
