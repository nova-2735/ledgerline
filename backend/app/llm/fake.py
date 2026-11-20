"""Fake provider: returns the generator's ground truth, looked up by document sha256.

Used by tests, seeding and offline demos. It never touches the network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.extraction import DocumentRead, RawInvoice
from app.models.reference import PurchaseOrder

from .base import CallMeta, FakeProviderError, LineGroup, LLMClient
from .prompts import load_prompt

FAKE_MODEL = "fake-truth"


class FakeClient(LLMClient):
    provider = "fake"
    is_live = False

    def __init__(self, settings: Settings, truth_dir: Path | None = None) -> None:
        self.model = FAKE_MODEL
        self.model_light = FAKE_MODEL
        self.truth_dir = truth_dir or settings.data_dir / "demo" / "truth"

    def _index(self) -> dict[str, str]:
        path = self.truth_dir / "index.json"
        if not path.is_file():
            raise FakeProviderError(f"no ground-truth index at {path}; run `make generate`")
        index: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        return index

    def truth_for(self, sha256: str) -> dict[str, Any]:
        doc_id = self._index().get(sha256)
        if doc_id is None:
            raise FakeProviderError("the fake provider only knows the generated demo documents")
        truth: dict[str, Any] = json.loads(
            (self.truth_dir / f"{doc_id}.json").read_text(encoding="utf-8")
        )
        return truth

    def extract_invoice(self, pdf_bytes: bytes, doc: DocumentRead) -> tuple[RawInvoice, CallMeta]:
        prompt = load_prompt("extract_invoice")
        sha = doc.sha256 or hashlib.sha256(pdf_bytes).hexdigest()
        raw = RawInvoice.model_validate(self.truth_for(sha)["raw"])
        meta = CallMeta(
            provider=self.provider,
            model=self.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            latency_ms=0,
        )
        return raw, meta

    def _meta(self, prompt_id: str) -> CallMeta:
        prompt = load_prompt(prompt_id)
        return CallMeta(
            provider=self.provider,
            model=self.model_light,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            latency_ms=0,
        )

    def map_lines(self, inv: RawInvoice, po: PurchaseOrder) -> tuple[list[LineGroup], CallMeta]:
        return [], self._meta("map_lines")

    def polish(self, summary: str, facts: dict[str, Any]) -> tuple[str, CallMeta]:
        return summary, self._meta("polish_explanation")
