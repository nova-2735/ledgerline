from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import TEST_TODAY

EXPECTED_KEYS = {
    "status",
    "version",
    "app_env",
    "llm_provider",
    "llm_model",
    "llm_model_light",
    "ocr_available",
    "db",
    "today",
}


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.keys() >= EXPECTED_KEYS
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_test_env_forces_fake_provider_and_pins_today(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("OCR_ENABLED", "1")
    get_settings.cache_clear()
    body = client.get("/api/health").json()
    assert body["app_env"] == "test"
    assert body["llm_provider"] == "fake"
    assert body["ocr_available"] is False
    assert body["today"] == TEST_TODAY


def test_clock_honours_app_today() -> None:
    assert clock.today().isoformat() == TEST_TODAY
    now = clock.now()
    assert now.utcoffset() is not None and now.utcoffset().total_seconds() == 0
    assert now.astimezone(clock.IST).date().isoformat() == TEST_TODAY


def test_production_refuses_fake_without_opt_in() -> None:
    with pytest.raises(ValueError, match="ALLOW_FAKE_LLM"):
        Settings(app_env="production", llm_provider="fake", allow_fake_llm=False)
    ok = Settings(app_env="production", llm_provider="fake", allow_fake_llm=True)
    assert ok.llm_provider == "fake"


def test_spa_served_for_non_api_paths(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log(1)", encoding="utf-8")
    with TestClient(create_app(static_dir=static)) as c:
        assert c.get("/runs/abc").text == "<html>spa</html>"
        assert c.get("/app.js").text == "console.log(1)"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/api/health").status_code == 200
