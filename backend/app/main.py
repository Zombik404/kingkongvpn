"""ASGI entrypoint: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from app.api.v1 import router as api_v1
from app.core.config import Settings, get_settings
from app.core.context import AppContext
from app.core.errors import AppError

log = logging.getLogger("app")

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "route"])

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-site",
}


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    settings = settings or (ctx.settings if ctx else get_settings())
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        own = ctx is None
        app.state.ctx = ctx or AppContext.create(settings)
        try:
            yield
        finally:
            if own:
                await app.state.ctx.close()

    public_docs = settings.app_env != "production"
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json" if public_docs else None,
        docs_url="/api/docs" if public_docs else None,
        redoc_url=None,
    )
    if ctx is not None:
        app.state.ctx = ctx

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Accept-Language", "X-Client-Version"],
        max_age=600,
    )

    @app.middleware("http")
    async def headers_and_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse({"error": body}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready(request: Request) -> JSONResponse:
        c: AppContext = request.app.state.ctx
        checks: dict[str, str] = {}
        try:
            async with c.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            log.exception("readiness: database")
            checks["database"] = "error"
        try:
            await c.redis.ping()
            checks["redis"] = "ok"
        except Exception:
            log.exception("readiness: redis")
            checks["redis"] = "error"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503
        )

    if settings.prometheus_metrics_enabled:
        # Expose only on the internal network: Nginx must not proxy /metrics publicly.
        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(api_v1)
    return app


def __getattr__(name: str) -> FastAPI:
    # Lazy so importing app.main (e.g. for OpenAPI export) doesn't require env settings.
    if name == "app":
        return create_app()
    raise AttributeError(name)
