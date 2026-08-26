"""Shared HTTP boundary for independently deployable sandbox services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

from changeops_core import configure_logging, get_logger, get_settings
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from changeops_sandbox.errors import SandboxError, TenantRequiredError


def _request_id(request: Request) -> str:
    value = request.headers.get("X-Request-ID", "").strip()
    if (
        value
        and len(value) <= 128
        and all(character.isalnum() or character in "-_." for character in value)
    ):
        return value
    return f"req_{uuid4().hex}"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _request_id(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


async def require_tenant(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> str:
    if x_tenant_id is None or not x_tenant_id.strip():
        raise TenantRequiredError
    tenant_id = x_tenant_id.strip()
    if len(tenant_id) > 128:
        raise TenantRequiredError
    return tenant_id


TenantId = Annotated[str, Depends(require_tenant)]


def create_sandbox_app(*, title: str, component: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        settings = get_settings()
        configure_logging(settings.log_level)
        get_logger(component).info(
            "sandbox_service_started",
            environment=settings.app_env,
            production_writes_enabled=settings.production_writes_enabled,
        )
        yield

    app = FastAPI(
        title=title,
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(SandboxError)
    async def sandbox_error_handler(request: Request, error: SandboxError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "request_id": request.state.request_id,
                    "details": [
                        {
                            "type": detail.get("type"),
                            "loc": detail.get("loc"),
                            "msg": detail.get("msg"),
                        }
                        for detail in error.errors()
                    ],
                }
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": component, "environment": "sandbox"}

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok", "service": component}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, str]:
        return {"status": "ready", "service": component}

    return app
