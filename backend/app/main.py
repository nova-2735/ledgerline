"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__, clock, db
from app.api import ROUTERS
from app.api.deps import APIError
from app.config import get_settings
from app.ingest.ocr import ocr_available
from app.models.api import HealthResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"


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


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    yield


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
        app.include_router(router, prefix="/api")
    _mount_spa(app, static_dir or STATIC_DIR)
    return app


app = create_app()
