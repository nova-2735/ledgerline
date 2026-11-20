"""Provider-neutral LLM interface. The model transcribes and suggests; it never decides."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.config import LLMProvider, Settings
from app.models.extraction import DocumentRead, RawInvoice
from app.models.reference import PurchaseOrder


class LLMError(RuntimeError):
    """Base class for provider errors. `retryable` marks transient failures."""

    retryable = False
    status_code: int | None = None


class LLMConfigError(LLMError):
    """Provider can't be used as configured (missing key, unknown provider)."""


class LLMRateLimitError(LLMError):
    retryable = True


class LLMUnavailableError(LLMError):
    retryable = True


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRequestError(LLMError):
    """The provider rejected the request (bad model name, schema not accepted, auth)."""


class LLMResponseError(LLMError):
    """The provider answered, but not with output we can use."""


class BudgetExceededError(LLMError):
    """Too many live model calls in the last hour (MAX_LIVE_LLM_CALLS_PER_HOUR)."""


class FakeProviderError(LLMError):
    """The fake provider has no ground truth for this document."""


@dataclass
class CallMeta:
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached: bool = False
    cached_at: datetime | None = None
    attempts: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_ref(self) -> str:
        return f"{self.prompt_id}@{self.prompt_version}"

    def event_data(self, kind: str) -> dict[str, Any]:
        """The `llm_call` payload of a run event (same keys as the extraction call)."""
        return {
            "kind": kind,
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt_ref,
            "latency_ms": self.latency_ms,
            "tokens_in": self.input_tokens,
            "tokens_out": self.output_tokens,
            "cached": self.cached,
            "attempts": self.attempts,
        }

    def describe(self) -> str:
        tokens = (
            f" · {self.input_tokens} in / {self.output_tokens} out tokens"
            if self.input_tokens is not None
            else ""
        )
        return f"{self.provider} · {self.model} ({self.prompt_ref}) in {self.latency_ms} ms{tokens}"


class LineGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_lines: list[int]
    po_lines: list[int]
    kind: Literal["one_to_one", "bundle", "split", "unmatched"]
    rationale: str


def validate_line_groups(
    groups: Sequence[LineGroup], invoice_count: int, po_line_numbers: Sequence[int]
) -> list[LineGroup]:
    """Reject suggestions that invent indexes, list an invoice line twice, or repeat a PO line
    within a group (a bundle of [1, 1] would bill line 1 twice)."""
    seen: set[int] = set()
    valid_po = set(po_line_numbers)
    for g in groups:
        for i in g.invoice_lines:
            if not 0 <= i < invoice_count or i in seen:
                raise LLMResponseError(f"line mapping uses invalid invoice line {i}")
            seen.add(i)
        for n in g.po_lines:
            if n not in valid_po:
                raise LLMResponseError(f"line mapping uses unknown PO line {n}")
        if len(set(g.po_lines)) != len(g.po_lines):
            raise LLMResponseError(f"line mapping repeats a PO line in {g.po_lines}")
        if g.kind == "unmatched" and g.po_lines:
            raise LLMResponseError("an unmatched group can't name PO lines")
    return list(groups)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _NUMBER.finditer(text)}


def polish_is_safe(original: str, rewritten: str) -> bool:
    """Every number of the template summary must survive the rewrite, and it must stay short."""
    if not rewritten.strip() or len(rewritten.split()) > 80:
        return False
    return numbers_in(original) <= numbers_in(rewritten)


class LLMClient(ABC):
    provider: str
    model: str
    model_light: str
    is_live: bool = True

    @abstractmethod
    def extract_invoice(self, pdf_bytes: bytes, doc: DocumentRead) -> tuple[RawInvoice, CallMeta]:
        """Transcribe a PDF into a RawInvoice (strings exactly as printed)."""

    @abstractmethod
    def map_lines(self, inv: RawInvoice, po: PurchaseOrder) -> tuple[list[LineGroup], CallMeta]:
        """Suggest invoice-line ↔ PO-line groups (validated; may be empty)."""

    @abstractmethod
    def polish(self, summary: str, facts: dict[str, Any]) -> tuple[str, CallMeta]:
        """Rewrite a template summary. The caller decides whether the rewrite is safe to use."""


def get_client(settings: Settings) -> LLMClient:
    if settings.llm_provider is LLMProvider.fake:
        from .fake import FakeClient

        return FakeClient(settings)
    if settings.llm_provider is LLMProvider.gemini:
        from .gemini import GeminiClient

        return GeminiClient(settings)
    raise LLMConfigError(f"provider {settings.llm_provider.value} is not available in this build")
