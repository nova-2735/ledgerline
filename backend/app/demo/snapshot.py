"""Fresh containers: restore the demo world and database seeded when the image was built.

The image seeds into `SNAPSHOT_DIR` at build time. On startup, when the SQLite database in
`DATA_DIR` doesn't exist yet (a new container, or an empty volume mounted on `DATA_DIR`), the
snapshot is copied in, so the app starts with the seeded history in about a second instead of
re-running the generator and the pipeline.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.config import REPO_ROOT, Settings

SNAPSHOT_DIR = REPO_ROOT / "seed-data"
DB_FILE = "ledgerline.db"


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
