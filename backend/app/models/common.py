"""Shared annotated types: Money, plain decimals and UTC datetimes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    WithJsonSchema,
)

CENT = Decimal("0.01")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal values must be given as strings, not floats")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int | str):
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal number: {value!r}") from exc
    else:
        raise ValueError(f"not a decimal number: {value!r}")
    if not result.is_finite():
        raise ValueError("decimal values must be finite")
    return result


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal_str(value: Decimal) -> str:
    return format(value, "f")


Money = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    AfterValidator(quantize_money),
    PlainSerializer(lambda v: _decimal_str(quantize_money(v)), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["116348.00"]}),
]
"""Amount of money: Decimal in Python, 2 dp ROUND_HALF_UP, string in JSON."""

Dec = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(_decimal_str, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["18"]}),
]
"""Quantity, rate or percentage: exact Decimal, string in JSON."""


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_to_utc)]
"""Timestamp normalised to UTC (naive values are taken as UTC)."""


class Model(BaseModel):
    """Base for API-facing models."""


class StrictModel(BaseModel):
    """Base for shapes that must not carry unknown keys."""

    model_config = ConfigDict(extra="forbid")
