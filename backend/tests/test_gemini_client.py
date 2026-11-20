"""Gemini client with the SDK replaced by a stub. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors, types

from app.config import Settings
from app.demo.invoice import build_printed, compute, load_specs, load_world, raw_invoice
from app.demo.templates import get_template
from app.llm.base import (
    LineGroup,
    LLMConfigError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    polish_is_safe,
    validate_line_groups,
)
from app.llm.gemini import GeminiClient, raw_invoice_schema
from app.models.extraction import DocumentRead


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "app_env": "development",
        "llm_provider": "gemini",
        "llm_model": "gemini-test-main",
        "llm_model_light": "gemini-test-light",
        "gemini_api_key": "test-key",
    }
    return Settings(**(base | kw))


def _s01_raw_json() -> str:
    world = load_world()
    spec = next(s for s in load_specs(world) if s.id == "S01")
    printed = build_printed(
        spec, compute(spec), world, get_template(spec.style.template).caps, False
    )
    return raw_invoice(spec, printed).model_dump_json()


DOC = DocumentRead(sha256="a" * 64, pages=[], doc_kind="digital", ocr_available=False, page_count=1)


class StubModels:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def list(self) -> list[Any]:
        return [
            SimpleNamespace(name="models/gemini-test-main", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/embed-1", supported_actions=["embedContent"]),
        ]


def _response(text: str | None, tokens: tuple[int, int, int] | None = (1200, 300, 40)) -> Any:
    usage = None
    if tokens:
        usage = SimpleNamespace(
            prompt_token_count=tokens[0],
            candidates_token_count=tokens[1],
            thoughts_token_count=tokens[2],
        )
    return SimpleNamespace(
        text=text, usage_metadata=usage, candidates=[SimpleNamespace(finish_reason="STOP")]
    )


def _client(outcomes: list[Any]) -> tuple[GeminiClient, StubModels, list[float]]:
    models = StubModels(outcomes)
    sleeps: list[float] = []
    client = GeminiClient(_settings(), sdk=SimpleNamespace(models=models), sleep=sleeps.append)
    return client, models, sleeps


def _api_error(code: int) -> errors.APIError:
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": f"status {code}", "status": "X"}})


def test_extract_invoice_request_and_parse() -> None:
    client, models, sleeps = _client([_response(_s01_raw_json())])
    raw, meta = client.extract_invoice(b"%PDF-1.7 fake", DOC)
    assert raw.invoice_number == "SPI/26-27/0214"
    assert meta.provider == "gemini" and meta.model == "gemini-test-main"
    assert meta.prompt_ref == "extract_invoice@v1"
    assert (meta.input_tokens, meta.output_tokens, meta.attempts) == (1200, 340, 1)
    assert sleeps == []
    (call,) = models.calls
    assert call["model"] == "gemini-test-main"
    config = call["config"]
    assert config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == raw_invoice_schema()
    part = call["contents"][0]
    assert isinstance(part, types.Part) and part.inline_data.mime_type == "application/pdf"
    assert "Transcribe, never compute" in call["contents"][1]


def test_schema_is_inlined() -> None:
    text = json.dumps(raw_invoice_schema())
    assert "$ref" not in text and "$defs" not in text
    schema = raw_invoice_schema()
    assert schema["additionalProperties"] is False
    assert "line_items" in schema["required"]


def test_retries_rate_limit_then_succeeds() -> None:
    client, models, sleeps = _client([_api_error(429), _api_error(503), _response(_s01_raw_json())])
    _, meta = client.extract_invoice(b"pdf", DOC)
    assert meta.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert len(models.calls) == 3


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (_api_error(429), LLMRateLimitError),
        (_api_error(503), LLMUnavailableError),
        (httpx.ReadTimeout("slow"), LLMTimeoutError),
    ],
)
def test_gives_up_after_three_attempts(failure: Exception, error: type[Exception]) -> None:
    client, models, sleeps = _client([failure, failure, failure])
    with pytest.raises(error):
        client.extract_invoice(b"pdf", DOC)
    assert len(models.calls) == 3 and sleeps == [1.0, 2.0]


def test_client_errors_are_not_retried() -> None:
    client, models, sleeps = _client([_api_error(400)])
    with pytest.raises(LLMRequestError, match="400"):
        client.extract_invoice(b"pdf", DOC)
    assert len(models.calls) == 1 and sleeps == []


@pytest.mark.parametrize("text", ["not json", '{"invoice_number": "X"}', None])
def test_bad_output_is_a_response_error(text: str | None) -> None:
    client, _, _ = _client([_response(text)])
    with pytest.raises(LLMResponseError):
        client.extract_invoice(b"pdf", DOC)


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(_settings(gemini_api_key=None))
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        client.extract_invoice(b"pdf", DOC)


def test_map_lines_validated() -> None:
    world = load_world()
    po = world.purchase_orders["KF-PO-0133"]
    spec = next(s for s in load_specs(world) if s.id == "S07")
    printed = build_printed(spec, compute(spec), world, get_template("modern").caps, False)
    inv = raw_invoice(spec, printed)
    good = json.dumps(
        [
            {
                "invoice_lines": [0],
                "po_lines": [1, 2],
                "kind": "bundle",
                "rationale": "incl. onboarding",
            }
        ]
    )
    client, models, _ = _client([_response(good)])
    groups = client.map_lines(inv, po)
    assert groups[0].kind == "bundle" and groups[0].po_lines == [1, 2]
    assert models.calls[0]["model"] == "gemini-test-light"
    bad = json.dumps(
        [{"invoice_lines": [0], "po_lines": [7], "kind": "one_to_one", "rationale": "x"}]
    )
    client, _, _ = _client([_response(bad)])
    with pytest.raises(LLMResponseError):
        client.map_lines(inv, po)


def test_validate_line_groups_rejects_duplicates() -> None:
    g = LineGroup(invoice_lines=[0], po_lines=[1], kind="one_to_one", rationale="")
    with pytest.raises(LLMResponseError):
        validate_line_groups([g, g], 1, [1])


def test_polish_guard() -> None:
    summary = "HOLD: invoice AIS/26-27/1188 bills 50 boxes but only 40 remain on KF-PO-0119."
    good = "HOLD. Invoice AIS/26-27/1188 asks for 50 boxes, yet only 40 remain open on KF-PO-0119."
    dropped = "HOLD. The invoice bills more boxes than remain on the order."
    assert polish_is_safe(summary, good)
    assert not polish_is_safe(summary, dropped)
    client, _, _ = _client([_response(good)])
    assert client.polish(summary, {}) == good
    client, _, _ = _client([_response(dropped)])
    assert client.polish(summary, {}) == summary
    client, _, _ = _client([_api_error(400)])
    assert client.polish(summary, {}) == summary


def test_list_models() -> None:
    client, _, _ = _client([])
    assert client.list_models() == ["gemini-test-main"]
