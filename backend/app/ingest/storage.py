"""Document storage: bytes in the `documents` table (deduplicated by sha256) plus a file copy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.db import get_sessionmaker
from app.orm import DocumentRow


@dataclass(frozen=True)
class StoredDocument:
    id: int
    sha256: str
    filename: str
    page_count: int
    path: Path
    created: bool  # False when the same bytes were already stored


def upload_path(sha256: str) -> Path:
    return get_settings().data_dir / "uploads" / f"{sha256}.pdf"


def _safe_name(filename: str) -> str:
    name = PurePath(filename.replace("\\", "/")).name.strip() or "document.pdf"
    return name[:255]


def _write_copy(path: Path, data: bytes) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def ensure_file(sha256: str, data: bytes) -> Path:
    """The on-disk copy of a stored document, rewritten from the database if it went missing."""
    path = upload_path(sha256)
    _write_copy(path, data)
    return path


def _to_stored(row: DocumentRow, created: bool) -> StoredDocument:
    return StoredDocument(
        id=row.id,
        sha256=row.sha256,
        filename=row.filename,
        page_count=row.page_count,
        path=upload_path(row.sha256),
        created=created,
    )


def _store(session: Session, data: bytes, filename: str) -> StoredDocument:
    from .reader import validate_pdf

    info = validate_pdf(data)
    _write_copy(upload_path(info.sha256), data)
    existing = session.scalar(select(DocumentRow).where(DocumentRow.sha256 == info.sha256))
    if existing is not None:
        return _to_stored(existing, created=False)
    row = DocumentRow(
        sha256=info.sha256,
        filename=_safe_name(filename),
        bytes=data,
        page_count=info.page_count,
        created_at=clock.now(),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        row = session.scalars(select(DocumentRow).where(DocumentRow.sha256 == info.sha256)).one()
        return _to_stored(row, created=False)
    return _to_stored(row, created=True)


def store_document(data: bytes, filename: str, session: Session | None = None) -> StoredDocument:
    """Validate and store a PDF. Raises `IntakeError` for files that can't be accepted."""
    if session is not None:
        return _store(session, data, filename)
    with get_sessionmaker()() as own:
        return _store(own, data, filename)
