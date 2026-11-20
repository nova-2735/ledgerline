"""Model-response cache in the `llm_cache` table, keyed by content hash + prompt version + model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import clock
from app.db import get_sessionmaker
from app.orm import LLMCacheRow


def cache_key(kind: str, content_sha256: str, prompt_ref: str, model: str) -> str:
    digest = hashlib.sha256(f"{content_sha256}|{prompt_ref}|{model}".encode()).hexdigest()
    return f"{kind}:{digest}"


@dataclass(frozen=True)
class CacheEntry:
    response: dict[str, Any]
    created_at: datetime


class LLMCache:
    def __init__(self, factory: sessionmaker[Session] | None = None) -> None:
        self._factory = factory

    def _session(self) -> Session:
        return (self._factory or get_sessionmaker())()

    def get(self, key: str) -> CacheEntry | None:
        with self._session() as s:
            row = s.scalar(select(LLMCacheRow).where(LLMCacheRow.key == key))
            return None if row is None else CacheEntry(dict(row.response), row.created_at)

    def put(
        self,
        key: str,
        *,
        kind: str,
        provider: str,
        model: str,
        prompt_version: str,
        response: dict[str, Any],
    ) -> None:
        with self._session() as s:
            existing = s.scalar(select(LLMCacheRow).where(LLMCacheRow.key == key))
            if existing is not None:
                existing.response = response
                existing.created_at = clock.now()
            else:
                s.add(
                    LLMCacheRow(
                        key=key,
                        kind=kind,
                        provider=provider,
                        model=model,
                        prompt_version=prompt_version,
                        response=response,
                        created_at=clock.now(),
                    )
                )
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
