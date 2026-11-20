from __future__ import annotations

from typing import Any

import pytest

from app.enums import Route, Severity
from app.models.checks import POCandidate
from app.rules import po as p
from app.rules.base import Resolution, ReviewOverrides, RuleContext
from tests.rules.builders import codes, make_ctx, make_extraction, policy, statuses

CAND = [
    POCandidate(po_number="KF-PO-0151", score=0.96, components={}, reason="items match"),
    POCandidate(po_number="KF-PO-0110", score=0.42, components={}, reason="fully billed"),
]


def _ctx(po_ref: str | None, method: str, po: str | None, **kw: Any) -> RuleContext:
    ctx = make_ctx(
        make_extraction(po_reference=po_ref), vendor="V004", po=po, po_method=method, **kw
    )  # type: ignore[arg-type]
    ctx.po_candidates = list(CAND)
    return ctx


@pytest.mark.parametrize(
    ("po_ref", "method", "po", "p01", "p02"),
    [
        ("KF-PO-0151", "explicit", "KF-PO-0151", [], "skip"),
        ("KF-PO-9999", "inferred_ref_miss", "KF-PO-0151", ["PO_INFERRED"], "skip"),
        ("KF-PO-9999", "not_found", None, ["PO_NOT_FOUND"], "skip"),
        (None, "inferred", "KF-PO-0151", "skip", ["PO_INFERRED"]),
        (None, "ambiguous", None, "skip", ["PO_AMBIGUOUS"]),
        (None, "missing", None, "skip", ["PO_MISSING"]),
    ],
)
def test_p01_p02_methods(
    po_ref: str | None, method: str, po: str | None, p01: Any, p02: Any
) -> None:
    ctx = _ctx(po_ref, method, po)
    for fn, want in ((p.p01_explicit, p01), (p.p02_inference, p02)):
        results = fn(ctx)
        if want == "skip":
            assert statuses(results) == ["skip"]
        else:
            assert codes(results) == want


def test_p02_routes_and_severity() -> None:
    [inferred] = p.p02_inference(_ctx(None, "inferred", "KF-PO-0151"))
    assert inferred.route == Route.ap_clerk and inferred.severity == Severity.medium
    assert "KF-PO-0151" in inferred.message and inferred.evidence["po_number"] == "KF-PO-0151"
    [missing] = p.p02_inference(_ctx(None, "missing", None))
    assert missing.route == Route.buyer and missing.severity == Severity.high
    [miss] = p.p01_explicit(_ctx("KF-PO-9999", "inferred_ref_miss", "KF-PO-0151"))
    assert miss.evidence["note"] == "printed ref not found"


def test_p02_auto_accept() -> None:
    pol = policy()
    auto = pol.model_copy(
        update={"po_inference": pol.po_inference.model_copy(update={"auto_accept_inferred": True})}
    )
    assert statuses(p.p02_inference(_ctx(None, "inferred", "KF-PO-0151", pol=auto))) == ["pass"]


def test_confirmed_po_resolves_inference() -> None:
    overrides = ReviewOverrides(
        po_number="KF-PO-0151",
        resolutions={"po_number": Resolution(reviewer="Priya Nair (AP)", note="Matches GRN-0951")},
    )
    ctx = _ctx(None, "inferred", "KF-PO-0151", po_confirmed=True, overrides=overrides)
    [res] = p.p02_inference(ctx)
    assert res.code == "PO_INFERRED" and res.resolved_by_review
    assert "Priya Nair (AP)" in res.message


def test_p03_vendor() -> None:
    assert codes(p.p03_vendor(make_ctx())) == []
    assert codes(p.p03_vendor(make_ctx(vendor="V004"))) == ["PO_VENDOR_MISMATCH"]
    [unknown] = p.p03_vendor(make_ctx(vendor=None))
    assert unknown.code == "PO_VENDOR_MISMATCH" and "not in the vendor master" in unknown.message
    assert statuses(p.p03_vendor(make_ctx(po=None))) == ["skip"]


def test_p04_status() -> None:
    ctx = make_ctx()
    assert codes(p.p04_status(ctx)) == []
    assert ctx.po is not None
    ctx.po = ctx.po.model_copy(update={"status": "closed"})
    assert codes(p.p04_status(ctx)) == ["PO_CLOSED"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, []),
        ({"currency": "USD"}, ["CURRENCY_MISMATCH"]),
        ({"invoice_date": "27/10/2026"}, ["DATE_BEFORE_PO"]),  # PO dated 28 Oct
        ({"invoice_date": "28/10/2026"}, []),
    ],
)
def test_p05_currency_date(overrides: dict[str, Any], expected: list[str]) -> None:
    assert codes(p.p05_currency_date(make_ctx(make_extraction(**overrides)))) == expected
