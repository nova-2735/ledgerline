"""FastAPI application factory."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import __version__, clock, db
from app.config import OCRMode, Settings, get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


def ocr_available(settings: Settings) -> bool:
    if settings.ocr_enabled is OCRMode.off:
        return False
    return shutil.which("tesseract") is not None


def _health_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, object]:
        settings = get_settings()
        return {
            "status": "ok",
            "version": __version__,
            "app_env": settings.app_env.value,
            "llm_provider": settings.llm_provider.value,
            "llm_model": settings.llm_model,
            "llm_model_light": settings.llm_model_light,
            "ocr_available": ocr_available(settings),
            "db": "ok" if db.ping() else "error",
            "today": clock.today().isoformat(),
        }

    return router


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        return
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(static_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Ledgerline", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(_health_router(), prefix="/api")
    _mount_spa(app, static_dir or STATIC_DIR)
    return app


app = create_app()
