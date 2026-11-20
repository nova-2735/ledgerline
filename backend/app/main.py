"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__, clock, db
from app.api import ROUTERS
from app.api.deps import APIError, require_access
from app.config import get_settings
from app.demo.snapshot import restore_if_missing
from app.ingest.ocr import ocr_available
from app.llm.base import warm_client
from app.models.api import HealthResponse
from app.pipeline import runner

STATIC_DIR = Path(__file__).resolve().parent / "static"
log = logging.getLogger("uvicorn.error")  # shown by uvicorn's default log config


def _health_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        settings = get_settings()
        return HealthResponse(
            status="ok",
            version=__version__,
            app_env=settings.app_env.value,
            llm_provider=settings.llm_provider.value,
            llm_model=settings.llm_model,
            llm_model_light=settings.llm_model_light,
            ocr_available=ocr_available(),
            db="ok" if db.ping() else "error",
            today=clock.today(),
        )

    return router


def _error_body(detail: str, code: str) -> dict[str, str]:
    return {"detail": detail, "code": code}


def _status_code_name(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(_error_body(exc.detail, exc.code), status_code=exc.status_code)

    @app.exception_handler(runner.ResetInProgress)
    async def reset_in_progress(_: Request, exc: runner.ResetInProgress) -> JSONResponse:
        return JSONResponse(_error_body(str(exc), "reset_in_progress"), status_code=409)

    @app.exception_handler(runner.ResetTimeout)
    async def reset_timeout(_: Request, exc: runner.ResetTimeout) -> JSONResponse:
        return JSONResponse(_error_body(str(exc), "reset_timeout"), status_code=409)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _error_body(str(exc.detail), _status_code_name(exc.status_code)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else err.get("msg", ""))
        return JSONResponse(_error_body("; ".join(parts), "validation_error"), status_code=422)


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        return
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def _operation_id(route: APIRoute) -> str:
    return route.name


def startup_line(restored: bool) -> str:
    """One log line saying what this instance runs with (provider, model, OCR, data)."""
    s = get_settings()
    ocr = "available" if ocr_available() else "not available (the model reads scanned pages)"
    data = "restored the seeded demo data" if restored else f"data in {s.data_dir}"
    return (
        f"Ledgerline {__version__} | {s.app_env.value} | provider {s.llm_provider.value} | "
        f"model {s.llm_model} / {s.llm_model_light} | OCR {ocr} | {data} | "
        f"{s.workers} worker{'s' if s.workers != 1 else ''}"
    )


def _warm_model_client() -> None:
    took = warm_client(get_settings())
    if took is not None:
        log.info(f"Model client ready in {took} ms")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    restored = restore_if_missing(get_settings())
    db.init_db()
    log.info(startup_line(restored))
    # Load the provider SDK off the request path: on a small instance its import takes seconds,
    # which the first live run would otherwise wait for.
    threading.Thread(target=_warm_model_client, name="warm-llm", daemon=True).start()
    yield
    from app.pipeline import runner

    runner.shutdown()


def create_app(static_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Ledgerline",
        version=__version__,
        lifespan=_lifespan,
        generate_unique_id_function=_operation_id,
        separate_input_output_schemas=False,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _install_error_handlers(app)
    app.include_router(_health_router(), prefix="/api")
    for router in ROUTERS:
        app.include_router(router, prefix="/api", dependencies=[Depends(require_access)])
    _mount_spa(app, static_dir or STATIC_DIR)
    return app


app = create_app()
