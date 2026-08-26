"""FastAPI application factory and stable HTTP boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Any
from uuid import uuid4

from changeops_core import (
    InvalidStateTransitionError,
    Settings,
    configure_logging,
    get_logger,
    get_settings,
)
from changeops_persistence import (
    AuditCursorNotFoundError,
    ChangeAlreadyExistsError,
    ChangeNotFoundError,
    ChangeStateRepository,
    InvalidDocumentIdentifierError,
    OptimisticConcurrencyError,
    PersistenceError,
    TenantScopeViolationError,
)
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from control_api.errors import ControlApiError
from control_api.models import HealthResponse, ServiceResponse
from control_api.repository import build_repository
from control_api.routes import build_router


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
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        request.state.request_id = _request_id(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


def create_app(
    *,
    repository: ChangeStateRepository | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_repository = repository or build_repository(resolved_settings)
    configure_logging(resolved_settings.log_level)
    logger = get_logger("control-api")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "service_started",
            environment=resolved_settings.app_env.value,
            persistence_backend=resolved_settings.persistence_backend.value,
            production_writes_enabled=resolved_settings.production_writes_enabled,
        )
        yield
        logger.info("service_stopped")

    app = FastAPI(
        title="Enterprise ChangeOps Control API",
        version="0.3.0",
        description="Deterministic tenant-scoped control API for governed enterprise changes.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(ControlApiError)
    async def control_error_handler(request: Request, error: ControlApiError) -> JSONResponse:
        return _error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=[
                {
                    "type": detail.get("type"),
                    "loc": detail.get("loc"),
                    "msg": detail.get("msg"),
                }
                for detail in error.errors()
            ],
        )

    @app.exception_handler(ChangeNotFoundError)
    @app.exception_handler(TenantScopeViolationError)
    async def change_not_found_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=404,
            code="change_not_found",
            message="The change was not found.",
        )

    @app.exception_handler(ChangeAlreadyExistsError)
    async def change_conflict_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="change_already_exists",
            message="A different change already uses this identifier.",
        )

    @app.exception_handler(AuditCursorNotFoundError)
    async def cursor_not_found_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="audit_cursor_not_found",
            message="Last-Event-ID is not valid for this tenant and change.",
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_transition_handler(
        request: Request,
        error: InvalidStateTransitionError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="invalid_state_transition",
            message="The requested workflow transition is not allowed.",
            details=[
                {
                    "current": error.current,
                    "target": error.target,
                    "audit_event_id": error.audit_event_id,
                }
            ],
        )

    @app.exception_handler(OptimisticConcurrencyError)
    async def concurrency_handler(
        request: Request,
        error: OptimisticConcurrencyError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="version_conflict",
            message="The change version is stale.",
            details=[
                {
                    "expected_version": error.expected_version,
                    "actual_version": error.actual_version,
                }
            ],
        )

    @app.exception_handler(InvalidDocumentIdentifierError)
    async def invalid_identifier_handler(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="invalid_identifier",
            message="A resource identifier is invalid.",
        )

    @app.exception_handler(PersistenceError)
    async def persistence_error_handler(request: Request, error: PersistenceError) -> JSONResponse:
        logger.exception("persistence_failure", error_type=type(error).__name__)
        return _error_response(
            request,
            status_code=503,
            code="persistence_unavailable",
            message="Operational persistence is unavailable.",
        )

    app.include_router(build_router(resolved_repository))

    @app.get("/", response_model=ServiceResponse)
    async def service_metadata() -> ServiceResponse:
        return ServiceResponse(
            service="control-api",
            status="available",
            environment=resolved_settings.app_env.value,
            persistence_backend=resolved_settings.persistence_backend.value,
            production_writes_enabled=resolved_settings.production_writes_enabled,
        )

    @app.get("/health/live", response_model=HealthResponse)
    async def liveness(response: Response) -> HealthResponse:
        response.headers["Cache-Control"] = "no-store"
        return HealthResponse(service="control-api", status="ok")

    @app.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    )
    async def readiness(response: Response) -> HealthResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            await run_in_threadpool(partial(resolved_repository.check_ready))
        except Exception as error:
            logger.exception("persistence_readiness_failed", error_type=type(error).__name__)
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(service="control-api", status="unavailable")
        return HealthResponse(service="control-api", status="ready")

    return app
