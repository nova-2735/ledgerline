"""Seeded snapshots: a copy of the freshly seeded demo database that a reset restores in seconds.

Two places hold one:
- the image's build-time snapshot in `SNAPSHOT_DIR` (`/app/seed-data`): seeded with the image's
  own code, so it is always current. A fresh container copies it into `DATA_DIR` on startup
  (`restore_if_missing`), and `POST /demo/reset` restores its database.
- locally, `DATA_DIR/seed-snapshot/`, written after every full seed. It records a fingerprint of
  the code, prompts, policy, scenario specs and generated world, and is ignored once any of them
  changes, so a reset never brings back history decided by older rules.

A restore copies the snapshot into the live SQLite database with SQLite's online backup API, so
open connections stay valid and no WAL file is left pointing at the old pages. Saved model
readings (`llm_cache`) are carried over, as a full reseed would keep them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db
from app.config import REPO_ROOT, Settings

log = logging.getLogger(__name__)

SNAPSHOT_DIR = REPO_ROOT / "seed-data"
LOCAL_SNAPSHOT = "seed-snapshot"
DB_FILE = "ledgerline.db"
META_FILE = "snapshot.json"
KEEP_TABLE = "llm_cache"
_CACHE_COLUMNS = ("key", "kind", "provider", "model", "prompt_version", "response", "created_at")
_APP_DIR = Path(__file__).resolve().parents[1]
_FINGERPRINT_GLOBS = ("**/*.py", "**/*.md", "**/*.yaml")


def restore_if_missing(settings: Settings, snapshot: Path | None = None) -> bool:
    """Copy the build-time snapshot into `DATA_DIR` if its database is missing. True if copied.

    Does nothing with an explicit `DATABASE_URL` (e.g. Postgres) or when there's no snapshot
    (local development)."""
    source = snapshot or SNAPSHOT_DIR
    if settings.database_url or not (source / DB_FILE).is_file():
        return False
    if (settings.data_dir / DB_FILE).exists():
        return False
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, settings.data_dir, dirs_exist_ok=True)
    return True


# --- fingerprint ---------------------------------------------------------------------------------


def fingerprint(settings: Settings) -> str:
    """Hash of everything a seeded history depends on: app code and prompts, scenario specs,
    the policy file and the generated world's manifest."""
    h = hashlib.sha256()
    files = {p for g in _FINGERPRINT_GLOBS for p in _APP_DIR.glob(g) if "static" not in p.parts}
    for path in sorted(files):
        h.update(path.relative_to(_APP_DIR).as_posix().encode())
        h.update(path.read_bytes())
    for path in (settings.policy_path, settings.data_dir / "demo" / "manifest.json"):
        h.update(path.name.encode())
        h.update(path.read_bytes() if path.is_file() else b"-")
    return h.hexdigest()


# --- finding a snapshot --------------------------------------------------------------------------


def _sqlite_file(settings: Settings) -> Path | None:
    url = settings.resolved_database_url
    if settings.database_url and not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///"))


def local_dir(settings: Settings) -> Path:
    return settings.data_dir / LOCAL_SNAPSHOT


def _is_build_dir(settings: Settings, built_in: Path) -> bool:
    return settings.data_dir.resolve() == built_in.resolve()


def find_snapshot(settings: Settings, built_in: Path | None = None) -> Path | None:
    """The snapshot directory a reset can restore from, or None (then the reset reseeds)."""
    if _sqlite_file(settings) is None:
        return None
    image = built_in or SNAPSHOT_DIR
    if (image / DB_FILE).is_file() and not _is_build_dir(settings, image):
        return image
    local = local_dir(settings)
    try:
        meta = json.loads((local / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (local / DB_FILE).is_file() and meta.get("fingerprint") == fingerprint(settings):
        return local
    return None


# --- save and restore ----------------------------------------------------------------------------


def _raw(settings: Settings) -> Any:
    """A pooled DBAPI connection to the live database (caller closes it)."""
    return db.get_engine().raw_connection()


def save_local(settings: Settings, runs: int, built_in: Path | None = None) -> Path | None:
    """After a full seed, copy the live database into `DATA_DIR/seed-snapshot/`. Skipped for
    non-SQLite databases and when seeding the image's build-time snapshot itself."""
    if _sqlite_file(settings) is None or _is_build_dir(settings, built_in or SNAPSHOT_DIR):
        return None
    target = local_dir(settings)
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / f"{DB_FILE}.tmp"
    tmp.unlink(missing_ok=True)
    raw = _raw(settings)
    try:
        dst = sqlite3.connect(tmp)
        try:
            raw.driver_connection.backup(dst)
            dst.execute(f"DELETE FROM {KEEP_TABLE}")  # the live cache is carried over on restore
            dst.commit()
            dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file
        finally:
            dst.close()
    finally:
        raw.close()
    tmp.replace(target / DB_FILE)
    meta = {
        "fingerprint": fingerprint(settings),
        "runs": runs,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (target / META_FILE).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target


def _open_read_only(path: Path) -> sqlite3.Connection:
    # immutable: no -wal/-shm files are created next to the snapshot (it may be read-only).
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def restore(settings: Settings, source: Path) -> None:
    """Replace the live database's contents with the snapshot's, keeping saved model readings.
    The caller holds the reset lock (`runner.exclusive`). Raises `sqlite3.Error` on failure,
    leaving the live database as it was."""
    raw = _raw(settings)
    try:
        live: sqlite3.Connection = raw.driver_connection
        live.commit()
        cols = ", ".join(_CACHE_COLUMNS)
        cached = live.execute(f"SELECT {cols} FROM {KEEP_TABLE}").fetchall()
        src = _open_read_only(source / DB_FILE)
        try:
            src.backup(live)
        finally:
            src.close()
        marks = ", ".join("?" for _ in _CACHE_COLUMNS)
        live.executemany(f"INSERT OR REPLACE INTO {KEEP_TABLE} ({cols}) VALUES ({marks})", cached)
        live.commit()
    finally:
        raw.close()
    world = settings.data_dir / "demo"
    if not (world / "manifest.json").is_file() and (source / "demo" / "manifest.json").is_file():
        shutil.copytree(source / "demo", world, dirs_exist_ok=True)
    log.info("restored the seeded demo database from %s", source)
