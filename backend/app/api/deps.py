"""Shared API helpers: error type, DB session, access-code check, common response declarations."""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.api import ErrorResponse

# EventSource, <img>, <iframe> and download links can't send headers, so these accept `?code=`.
QUERY_CODE_SUFFIXES = ("/events", "/document", ".png", ".pdf")


class APIError(Exception):
    """An error rendered as `{"detail": str, "code": str}`."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


DB = Annotated[Session, Depends(get_db)]


def require_access(request: Request) -> None:
    """When DEMO_ACCESS_CODE is set, every route except /api/health needs it."""
    expected = get_settings().demo_access_code
    if expected is None:
        return
    given = request.headers.get("X-Access-Code")
    if given is None and request.url.path.endswith(QUERY_CODE_SUFFIXES):
        given = request.query_params.get("code")
    if given is None or not hmac.compare_digest(given, expected.get_secret_value()):
        raise APIError(401, "access_code_required", "A valid access code is required.")


def not_found(what: str) -> APIError:
    return APIError(404, "not_found", f"{what} not found.")


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Access code missing or wrong"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflict with the run's state"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
}
