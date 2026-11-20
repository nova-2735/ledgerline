"""Vendor checks (RULES §1.2, stage `identify_vendor`)."""

from __future__ import annotations

from app.enums import Outcome, ReasonCode, Route, Severity, StageName
from app.extract.normalize import mask_account, normalize_account, normalize_ifsc
from app.models.checks import CheckResult
from app.reference import gstin as gstin_util
from app.rules.base import Emitter, RuleContext, inr, rule, text_value

STAGE = StageName.identify_vendor
FREE_MAIL = frozenset({"gmail.com", "yahoo.com", "outlook.com", "mail.example"})


def _supplier_label(ctx: RuleContext) -> str:
    name = text_value(ctx.extraction.supplier_name)
    return name or ctx.vendor_match.invoice_gstin or "the supplier"


@rule("V01_resolve", STAGE)
def v01_resolve(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    m = ctx.vendor_match
    evidence = {
        "matched_by": m.matched_by,
        "score": m.score,
        "invoice_gstin": m.invoice_gstin,
        "invoice_name": text_value(ctx.extraction.supplier_name),
    }
    if m.vendor is not None and m.matched_by == "gstin":
        return [
            e.passed(
                "Vendor found",
                f"{m.vendor.legal_name} ({m.vendor.vendor_id}) matched by GSTIN {m.invoice_gstin}.",
                evidence | {"vendor_id": m.vendor.vendor_id},
            )
        ]
    if m.vendor is not None:
        return [
            e.warn(
                ReasonCode.VENDOR_MATCHED_BY_NAME,
                "Vendor matched by name",
                f"No GSTIN match; matched {m.vendor.legal_name} ({m.vendor.vendor_id}) by name "
                f'"{m.matched_name}" ({round(m.score * 100)}% similar).',
                severity=Severity.high,
                route=Route.procurement,
                evidence=evidence | {"vendor_id": m.vendor.vendor_id},
            )
        ]
    return [
        e.fail(
            ReasonCode.VENDOR_NOT_FOUND,
            "Vendor not in the vendor master",
            f"{_supplier_label(ctx)} is not in the vendor master (no GSTIN or name match). "
            "Procurement needs to onboard the vendor or reject the invoice.",
            severity=Severity.high,
            route=Route.procurement,
            hint=Outcome.HOLD,
            evidence=evidence,
            at_risk=ctx.total,
        )
    ]


@rule("V02_status", STAGE)
def v02_status(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    v = ctx.vendor
    if v is None:
        return [e.skip("Vendor status", "Vendor not identified.")]
    if v.status == "blocked":
        reason = f': "{v.block_reason}"' if v.block_reason else ""
        return [
            e.fail(
                ReasonCode.VENDOR_BLOCKED,
                "Vendor is blocked",
                f"{v.legal_name} is blocked in the vendor master{reason}. "
                "Invoices from blocked vendors are not paid.",
                severity=Severity.high,
                route=Route.none,
                hint=Outcome.REJECT,
                evidence={"vendor_id": v.vendor_id, "block_reason": v.block_reason},
                at_risk=ctx.total,
            )
        ]
    return [e.passed("Vendor is active", f"{v.legal_name} is active.")]


@rule("V03_gstin_consistency", STAGE)
def v03_gstin_consistency(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    m = ctx.vendor_match
    if m.vendor is None:
        return [e.skip("GSTIN matches vendor", "Vendor not identified.")]
    if m.matched_by == "gstin":
        return [e.passed("GSTIN matches vendor", f"GSTIN {m.invoice_gstin} is on file.")]
    on_file = gstin_util.clean(m.vendor.gstin)
    if m.invoice_gstin is None:
        return [e.passed("GSTIN matches vendor", "No GSTIN printed to compare.")]
    if m.invoice_gstin != on_file:
        return [
            e.fail(
                ReasonCode.VENDOR_GSTIN_MISMATCH,
                "GSTIN differs from vendor record",
                f"The invoice GSTIN {m.invoice_gstin} differs from the GSTIN on file for "
                f"{m.vendor.legal_name} ({on_file}).",
                severity=Severity.high,
                route=Route.ap_clerk,
                hint=Outcome.HOLD,
                evidence={"expected": on_file, "actual": m.invoice_gstin},
            )
        ]
    return [e.passed("GSTIN matches vendor", f"GSTIN {on_file} is on file.")]


def _bank_notice(ctx: RuleContext) -> list[str]:
    return [a for a in ctx.extraction.annotations if "bank" in a.lower()]


@rule("V04_bank_details", STAGE)
def v04_bank_details(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    v = ctx.vendor
    if v is None:
        return [e.skip("Bank details", "Vendor not identified.")]
    ex = ctx.extraction
    account = normalize_account(text_value(ex.bank_account_number))
    ifsc = normalize_ifsc(text_value(ex.bank_ifsc))
    if account is None and ifsc is None:
        return [
            e.passed(
                "No bank details printed",
                f"Payment will go to the account on file ({mask_account(v.bank_account_number)}).",
            )
        ]
    file_account = normalize_account(v.bank_account_number) or ""
    file_ifsc = normalize_ifsc(v.bank_ifsc) or ""
    account_differs = account is not None and account != file_account
    ifsc_differs = ifsc is not None and ifsc != file_ifsc
    on_file = f"{v.bank_name} {mask_account(file_account)}"
    if not (account_differs or ifsc_differs):
        return [
            e.passed("Bank account matches vendor record", f"Same account as on file ({on_file}).")
        ]
    printed_bank = text_value(ex.bank_name) or "another bank"
    printed = f"{printed_bank} {mask_account(account)}" if account else printed_bank
    phone = text_value(ex.supplier_phone)
    evidence = {
        "on_file": {
            "bank_name": v.bank_name,
            "account": mask_account(file_account),
            "ifsc": file_ifsc,
            "phone": v.phone_on_file,
        },
        "invoice": {
            "bank_name": text_value(ex.bank_name),
            "account": mask_account(account) if account else None,
            "ifsc": ifsc,
            "phone": phone,
        },
        "account_differs": account_differs,
        "ifsc_differs": ifsc_differs,
        "notice": _bank_notice(ctx),
    }
    call = f" Call the number on file ({v.phone_on_file}), not the one on the invoice."
    result = e.fail(
        ReasonCode.BANK_DETAILS_CHANGED,
        "Bank details differ from vendor record",
        f"The invoice asks for payment to {printed}"
        + (f" (IFSC {ifsc})" if ifsc else "")
        + f", but the account on file is {on_file}. "
        f"Treasury must verify the change with {v.legal_name} before paying {inr(ctx.total)}."
        + call,
        severity=Severity.critical,
        route=Route.treasury,
        hint=Outcome.HOLD,
        evidence=evidence,
        at_risk=ctx.total,
    )
    return [ctx.resolve(result, "bank_verified")]


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower()


@rule("V05_sender", STAGE)
def v05_sender(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    sender = (ctx.sender_email or "").strip().lower()
    if not sender:
        return [e.skip("Sender address", "Uploaded directly; no sender to check.")]
    v = ctx.vendor
    if v is None:
        return [e.skip("Sender address", "Vendor not identified.")]
    on_file = v.email.strip().lower()
    free = _domain(on_file) in FREE_MAIL or _domain(sender) in FREE_MAIL
    same = sender == on_file if free else _domain(sender) == _domain(on_file)
    evidence = {"sender": sender, "on_file": on_file, "compared": "address" if free else "domain"}
    if same:
        return [e.passed("Sender matches vendor record", f"Sent from {sender}.", evidence)]
    what = "address" if free else "domain"
    return [
        e.warn(
            ReasonCode.SENDER_DOMAIN_MISMATCH,
            "Sender differs from vendor record",
            f"Sent from {sender}, but the email on file for {v.legal_name} is {on_file} "
            f"(different {what}). This can be a sign of invoice fraud.",
            severity=Severity.high,
            route=Route.treasury,
            evidence=evidence,
        )
    ]


RULES = [v01_resolve, v02_status, v03_gstin_consistency, v04_bank_details, v05_sender]
