"""SQLAlchemy tables (CONTRACTS §7). JSON columns hold Pydantic dumps."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Dialect,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.models.common import CENT, quantize_money


class MoneyType(TypeDecorator[Decimal]):
    """Money stored as integer paise: exact in SQLite and summable in SQL."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        return int(quantize_money(Decimal(value)) / CENT)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return quantize_money(Decimal(value) * CENT)


class DecimalType(TypeDecorator[Decimal]):
    """Exact decimal (quantities, rates) stored as text."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else format(Decimal(value), "f")

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class UtcDateTime(TypeDecorator[datetime]):
    """Timestamps stored as naive UTC, returned as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class CompanyRow(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str] = mapped_column(Text)


class VendorRow(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[Any]] = mapped_column(JSON, default=list)
    gstin: Mapped[str] = mapped_column(String(15), index=True)
    pan: Mapped[str] = mapped_column(String(10))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200))
    phone_on_file: Mapped[str] = mapped_column(String(40))
    bank_name: Mapped[str] = mapped_column(String(100))
    bank_account_number: Mapped[str] = mapped_column(String(40))
    bank_ifsc: Mapped[str] = mapped_column(String(11))
    status: Mapped[str] = mapped_column(String(20))
    block_reason: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(100))


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(40), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"), index=True)
    po_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    match_type: Mapped[str] = mapped_column(String(20))
    buyer_name: Mapped[str] = mapped_column(String(200))
    cost_center: Mapped[str] = mapped_column(String(40))

    vendor: Mapped[VendorRow] = relationship()
    lines: Mapped[list[POLineRow]] = relationship(
        back_populates="po", order_by="POLineRow.line_no", cascade="all, delete-orphan"
    )


class POLineRow(Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("po_number", "line_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(DecimalType)
    uom: Mapped[str] = mapped_column(String(20))
    unit_price: Mapped[Decimal] = mapped_column(MoneyType)
    tax_rate_pct: Mapped[Decimal] = mapped_column(DecimalType)
    hsn_sac: Mapped[str] = mapped_column(String(10))
    gl_account: Mapped[str] = mapped_column(String(20))

    po: Mapped[PurchaseOrderRow] = relationship(back_populates="lines")


class GoodsReceiptRow(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (UniqueConstraint("grn_number", "po_number", "line_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grn_number: Mapped[str] = mapped_column(String(40), index=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    quantity_received: Mapped[Decimal] = mapped_column(DecimalType)
    received_date: Mapped[date] = mapped_column(Date)


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    bytes: Mapped[bytes] = mapped_column(LargeBinary)
    page_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_id: Mapped[str] = mapped_column(String(20), unique=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    scenario_id: Mapped[str | None] = mapped_column(String(20))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    sender_email: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    checks: Mapped[list[Any] | None] = mapped_column(JSON)
    stages: Mapped[list[Any] | None] = mapped_column(JSON)
    matching: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decision_history: Mapped[list[Any] | None] = mapped_column(JSON)
    vendor_id: Mapped[str | None] = mapped_column(String(20), index=True)
    po_number: Mapped[str | None] = mapped_column(String(40), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_number_canonical: Mapped[str | None] = mapped_column(String(100), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal | None] = mapped_column(MoneyType)
    outcome: Mapped[str | None] = mapped_column(String(10), index=True)
    route: Mapped[str | None] = mapped_column(String(20), index=True)
    primary_reason: Mapped[str | None] = mapped_column(String(40))
    final_outcome: Mapped[str | None] = mapped_column(String(10))
    policy_version: Mapped[str | None] = mapped_column(String(40))
    cached_extraction: Mapped[bool] = mapped_column(Boolean, default=False)
    overrides: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    document: Mapped[DocumentRow] = relationship()
    events: Mapped[list[RunEventRow]] = relationship(
        back_populates="run", order_by="RunEventRow.seq", cascade="all, delete-orphan"
    )
    review_actions: Mapped[list[ReviewActionRow]] = relationship(
        back_populates="run", order_by="ReviewActionRow.id", cascade="all, delete-orphan"
    )


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(UtcDateTime)
    type: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    run: Mapped[RunRow] = relationship(back_populates="events")


class ReviewActionRow(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    reviewer: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text)
    po_number: Mapped[str | None] = mapped_column(String(40))
    field_corrections: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fields_verified: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    resulting_decision_version: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[RunRow] = relationship(back_populates="review_actions")


class InvoiceLedgerRow(Base):
    __tablename__ = "invoice_ledger"

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    vendor_id: Mapped[str | None] = mapped_column(String(20), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_number_canonical: Mapped[str | None] = mapped_column(String(100), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal | None] = mapped_column(MoneyType)
    po_number: Mapped[str | None] = mapped_column(String(40), index=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    final_outcome: Mapped[str | None] = mapped_column(String(10))
    billed_lines: Mapped[list[Any]] = mapped_column(JSON, default=list)


class LLMCacheRow(Base):
    __tablename__ = "llm_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(40))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
