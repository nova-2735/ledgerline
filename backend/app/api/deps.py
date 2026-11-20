"""Shared API helpers: error type and common response declarations."""

from __future__ import annotations

from typing import Any, NoReturn

from app.models.api import ErrorResponse


class APIError(Exception):
    """An error rendered as `{"detail": str, "code": str}`."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def not_implemented() -> NoReturn:
    raise APIError(501, "not_implemented", "not implemented")


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
    501: {"model": ErrorResponse, "description": "Not implemented yet"},
}
