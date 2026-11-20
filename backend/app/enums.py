"""Domain enums shared by models, ORM and API."""

from __future__ import annotations

from enum import StrEnum


class StageName(StrEnum):
    intake = "intake"
    read_document = "read_document"
    extract_fields = "extract_fields"
    validate_document = "validate_document"
    identify_vendor = "identify_vendor"
    check_tax = "check_tax"
    resolve_po = "resolve_po"
    match_lines = "match_lines"
    check_duplicates = "check_duplicates"
    decide = "decide"
    explain_route = "explain_route"


class StageStatus(StrEnum):
    pending = "pending"
    running = "running"
    passed = "passed"
    warned = "warned"
    failed = "failed"
    skipped = "skipped"
    error = "error"


class CheckStatus(StrEnum):
    pass_ = "pass"
    warn = "warn"
    fail = "fail"
    skip = "skip"


class Severity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Outcome(StrEnum):
    APPROVE = "APPROVE"
    HOLD = "HOLD"
    RETURN = "RETURN"
    REJECT = "REJECT"


class Route(StrEnum):
    none = "none"
    ap_clerk = "ap_clerk"
    buyer = "buyer"
    receiving = "receiving"
    treasury = "treasury"
    procurement = "procurement"
    controller = "controller"
    vendor = "vendor"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"
    completed = "completed"
    failed = "failed"


class RunSource(StrEnum):
    upload = "upload"
    demo = "demo"
    email = "email"
    seed = "seed"


class DocType(StrEnum):
    tax_invoice = "tax_invoice"
    proforma_invoice = "proforma_invoice"
    credit_note = "credit_note"
    debit_note = "debit_note"
    purchase_order = "purchase_order"
    receipt = "receipt"
    statement = "statement"
    other = "other"


class DocKind(StrEnum):
    digital = "digital"
    scanned = "scanned"
    mixed = "mixed"


class ConfidenceLevel(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class MatchType(StrEnum):
    three_way = "three_way"
    two_way = "two_way"


class ActionType(StrEnum):
    approve = "approve"
    reject = "reject"
    send_to_vendor = "send_to_vendor"
    confirm_po = "confirm_po"
    verify_bank = "verify_bank"
    correct_fields = "correct_fields"
    not_duplicate = "not_duplicate"
    reopen = "reopen"


class ReasonCode(StrEnum):
    DOC_NOT_INVOICE = "DOC_NOT_INVOICE"
    DOC_PROFORMA = "DOC_PROFORMA"
    DOC_CREDIT_NOTE = "DOC_CREDIT_NOTE"
    DOC_UNREADABLE = "DOC_UNREADABLE"
    FIELD_MISSING_INVOICE_NUMBER = "FIELD_MISSING_INVOICE_NUMBER"
    FIELD_MISSING_INVOICE_DATE = "FIELD_MISSING_INVOICE_DATE"
    FIELD_MISSING_TOTAL = "FIELD_MISSING_TOTAL"
    FIELD_MISSING_SUPPLIER = "FIELD_MISSING_SUPPLIER"
    FIELD_LOW_CONFIDENCE = "FIELD_LOW_CONFIDENCE"
    MATH_LINE_MISMATCH = "MATH_LINE_MISMATCH"
    MATH_SUBTOTAL_MISMATCH = "MATH_SUBTOTAL_MISMATCH"
    MATH_TOTAL_MISMATCH = "MATH_TOTAL_MISMATCH"
    ROUND_OFF_APPLIED = "ROUND_OFF_APPLIED"
    TAX_INCLUSIVE_NORMALIZED = "TAX_INCLUSIVE_NORMALIZED"
    TOTAL_WORDS_MISMATCH = "TOTAL_WORDS_MISMATCH"
    DATE_IN_FUTURE = "DATE_IN_FUTURE"
    DATE_STALE = "DATE_STALE"
    VENDOR_NOT_FOUND = "VENDOR_NOT_FOUND"
    VENDOR_BLOCKED = "VENDOR_BLOCKED"
    VENDOR_GSTIN_MISMATCH = "VENDOR_GSTIN_MISMATCH"
    VENDOR_MATCHED_BY_NAME = "VENDOR_MATCHED_BY_NAME"
    BANK_DETAILS_CHANGED = "BANK_DETAILS_CHANGED"
    SENDER_DOMAIN_MISMATCH = "SENDER_DOMAIN_MISMATCH"
    GSTIN_INVALID = "GSTIN_INVALID"
    BUYER_GSTIN_MISMATCH = "BUYER_GSTIN_MISMATCH"
    TAX_TYPE_MISMATCH = "TAX_TYPE_MISMATCH"
    TAX_AMOUNT_MISMATCH = "TAX_AMOUNT_MISMATCH"
    TAX_RATE_MISMATCH = "TAX_RATE_MISMATCH"
    PO_NOT_FOUND = "PO_NOT_FOUND"
    PO_INFERRED = "PO_INFERRED"
    PO_AMBIGUOUS = "PO_AMBIGUOUS"
    PO_MISSING = "PO_MISSING"
    PO_VENDOR_MISMATCH = "PO_VENDOR_MISMATCH"
    PO_CLOSED = "PO_CLOSED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    DATE_BEFORE_PO = "DATE_BEFORE_PO"
    LINE_NOT_ON_PO = "LINE_NOT_ON_PO"
    MISC_CHARGE_ALLOWED = "MISC_CHARGE_ALLOWED"
    LINES_BUNDLED = "LINES_BUNDLED"
    PRICE_VARIANCE_WITHIN_TOL = "PRICE_VARIANCE_WITHIN_TOL"
    PRICE_VARIANCE_OVER_TOL = "PRICE_VARIANCE_OVER_TOL"
    PRICE_BELOW_PO = "PRICE_BELOW_PO"
    AMOUNT_VARIANCE_OVER_TOL = "AMOUNT_VARIANCE_OVER_TOL"
    QTY_EXCEEDS_PO_REMAINING = "QTY_EXCEEDS_PO_REMAINING"
    QTY_EXCEEDS_RECEIVED = "QTY_EXCEEDS_RECEIVED"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED"
    DUPLICATE_SAME_FILE = "DUPLICATE_SAME_FILE"
    DUPLICATE_SAME_INVOICE = "DUPLICATE_SAME_INVOICE"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    APPROVAL_LIMIT_EXCEEDED = "APPROVAL_LIMIT_EXCEEDED"
