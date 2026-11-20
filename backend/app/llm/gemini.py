"""Gemini provider via the google-genai SDK. Every other module stays SDK-free."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.config import Settings
from app.models.extraction import DocumentRead, RawInvoice
from app.models.reference import PurchaseOrder

from .base import (
    CallMeta,
    LineGroup,
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    polish_is_safe,
    validate_line_groups,
)
from .prompts import load_prompt

MAX_ATTEMPTS = 3
BACKOFF_S = 1.0
_LINE_GROUPS = TypeAdapter(list[LineGroup])


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref`s against `$defs` and drop title noise, for providers that dislike refs."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = walk(defs[node["$ref"].rsplit("/", 1)[-1]])
                extra = {k: walk(v) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            return {
                k: walk(v)
                for k, v in node.items()
                if k != "$defs" and not (k == "title" and isinstance(v, str))
            }
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result: dict[str, Any] = walk(schema)
    return result


def raw_invoice_schema() -> dict[str, Any]:
    return inline_schema(RawInvoice.model_json_schema())


def line_groups_schema() -> dict[str, Any]:
    return {"type": "array", "items": inline_schema(LineGroup.model_json_schema())}


def classify_error(exc: Exception) -> LLMError:
    """Map SDK/transport exceptions to our error types (never includes the key)."""
    from google.genai import errors

    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        msg = f"Gemini API error {code}: {getattr(exc, 'message', '') or exc.__class__.__name__}"
        if code == 429:
            return LLMRateLimitError(msg)
        if code in (408, 504):
            return LLMTimeoutError(msg)
        if code >= 500:
            return LLMUnavailableError(msg)
        return LLMRequestError(msg)
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return LLMTimeoutError(f"Gemini call timed out ({exc.__class__.__name__})")
    if isinstance(exc, httpx.TransportError | ConnectionError):
        return LLMUnavailableError(f"Gemini unreachable ({exc.__class__.__name__})")
    return LLMError(f"Gemini call failed ({exc.__class__.__name__})")


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(
        self,
        settings: Settings,
        sdk: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.model = settings.llm_model
        self.model_light = settings.llm_model_light
        self._sdk = sdk
        self._sleep = sleep

    def _client(self) -> Any:
        if self._sdk is None:
            key = self.settings.gemini_api_key
            if key is None or not key.get_secret_value().strip():
                raise LLMConfigError("GEMINI_API_KEY is not set")
            from google import genai
            from google.genai import types

            self._sdk = genai.Client(
                api_key=key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(self.settings.llm_timeout_s * 1000)),
            )
        return self._sdk

    def _generate(self, model: str, contents: list[Any], config: Any) -> tuple[Any, int, int]:
        """Call generate_content with retries; returns (response, attempts, latency_ms)."""
        client = self._client()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            start = time.perf_counter()
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:
                err = classify_error(exc)
                if not err.retryable or attempt == MAX_ATTEMPTS:
                    raise err from exc
                self._sleep(BACKOFF_S * 2 ** (attempt - 1))
                continue
            return response, attempt, int((time.perf_counter() - start) * 1000)
        raise LLMError("unreachable")  # pragma: no cover

    @staticmethod
    def _text(response: Any) -> str:
        text = getattr(response, "text", None)
        if not text:
            reason = None
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                reason = getattr(candidates[0], "finish_reason", None)
            raise LLMResponseError(f"model returned no text (finish reason: {reason})")
        return str(text)

    @staticmethod
    def _usage(response: Any) -> tuple[int | None, int | None, dict[str, Any]]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None, None, {}
        prompt = getattr(usage, "prompt_token_count", None)
        out = getattr(usage, "candidates_token_count", None)
        thoughts = getattr(usage, "thoughts_token_count", None)
        total_out = None if out is None and thoughts is None else (out or 0) + (thoughts or 0)
        return prompt, total_out, {"thoughts_tokens": thoughts} if thoughts else {}

    def extract_invoice(self, pdf_bytes: bytes, doc: DocumentRead) -> tuple[RawInvoice, CallMeta]:
        from google.genai import types

        prompt = load_prompt("extract_invoice")
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=raw_invoice_schema(),
        )
        contents = [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt.text]
        response, attempts, latency = self._generate(self.model, contents, config)
        try:
            raw = RawInvoice.model_validate_json(self._text(response))
        except ValidationError as exc:
            raise LLMResponseError(
                f"model output did not match the invoice schema ({exc.error_count()} errors)"
            ) from exc
        tokens_in, tokens_out, extra = self._usage(response)
        meta = CallMeta(
            provider=self.provider,
            model=self.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            latency_ms=latency,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            attempts=attempts,
            extra=extra,
        )
        return raw, meta

    def map_lines(self, inv: RawInvoice, po: PurchaseOrder) -> list[LineGroup]:
        from google.genai import types

        prompt = load_prompt("map_lines")
        payload = {
            "invoice_lines": [
                {
                    "index": i,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "unit_price": ln.unit_price,
                    "amount": ln.amount,
                }
                for i, ln in enumerate(inv.line_items)
            ],
            "po_lines": [
                {
                    "line_no": ln.line_no,
                    "item_code": ln.item_code,
                    "description": ln.description,
                    "quantity": str(ln.quantity),
                    "unit_price": str(ln.unit_price),
                }
                for ln in po.lines
            ],
        }
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=line_groups_schema(),
        )
        contents = [prompt.text, json.dumps(payload, ensure_ascii=False)]
        response, _, _ = self._generate(self.model_light, contents, config)
        try:
            groups = _LINE_GROUPS.validate_json(self._text(response))
        except ValidationError as exc:
            raise LLMResponseError("line mapping did not match the expected shape") from exc
        return validate_line_groups(groups, len(inv.line_items), [ln.line_no for ln in po.lines])

    def polish(self, summary: str, facts: dict[str, Any]) -> str:
        from google.genai import types

        prompt = load_prompt("polish_explanation")
        contents = [
            prompt.text,
            f"Summary:\n{summary}\n\nFacts:\n{json.dumps(facts, ensure_ascii=False, default=str)}",
        ]
        try:
            response, _, _ = self._generate(
                self.model_light, contents, types.GenerateContentConfig(temperature=0)
            )
            rewritten = self._text(response).strip()
        except LLMError:
            return summary
        return rewritten if polish_is_safe(summary, rewritten) else summary

    def list_models(self) -> list[str]:
        """Model names this key can call with generateContent."""
        names: list[str] = []
        try:
            for m in self._client().models.list():
                actions = getattr(m, "supported_actions", None) or []
                if not actions or "generateContent" in actions:
                    names.append(str(m.name).removeprefix("models/"))
        except Exception as exc:
            raise classify_error(exc) from exc
        return sorted(names)
