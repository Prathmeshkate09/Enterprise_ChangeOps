"""Authenticated asynchronous change-event ingestion boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, ParamSpec, TypeVar
from uuid import uuid4

from changeops_contracts import ChangeEvent, derive_change_id
from changeops_core import PersistenceBackend, Settings, configure_logging, get_settings
from fastapi import FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from changeops_event_gateway.auth import WebhookSignatureVerifier
from changeops_event_gateway.errors import EventDependencyError, EventGatewayError
from changeops_event_gateway.firestore_repository import FirestoreEventInboxRepository
from changeops_event_gateway.models import EventAcceptedResponse, HealthResponse, InboxStatus
from changeops_event_gateway.publisher import EventPublisher, PubSubEventPublisher
from changeops_event_gateway.rate_limit import TenantEventRateLimiter
from changeops_event_gateway.repository import EventInboxRepository, InMemoryEventInboxRepository

P = ParamSpec("P")
R = TypeVar("R")


async def _run_sync(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    return await run_in_threadpool(partial(function, *args, **kwargs))


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "").strip()
        request.state.request_id = (
            supplied
            if supplied
            and len(supplied) <= 128
            and all(character.isalnum() or character in "-_." for character in supplied)
            else f"req_{uuid4().hex}"
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _problem(request: Request, error: EventGatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "type": f"https://changeops.example/problems/{error.code.lower()}",
            "title": error.code.replace("_", " ").title(),
            "status": error.status_code,
            "code": error.code,
            "detail": error.detail,
            "request_id": request.state.request_id,
        },
    )


def _repository(settings: Settings) -> EventInboxRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryEventInboxRepository()
    if settings.google_cloud_project is None:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for the Firestore event inbox.")
    return FirestoreEventInboxRepository.from_project(
        settings.google_cloud_project, settings.firestore_database
    )


def create_app(
    *,
    settings: Settings | None = None,
    repository: EventInboxRepository | None = None,
    publisher: EventPublisher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    if resolved.event_gateway_webhook_secret is None:
        raise ValueError("EVENT_GATEWAY_WEBHOOK_SECRET is required.")
    if resolved.google_cloud_project is None and publisher is None:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for Pub/Sub publication.")
    inbox = repository or _repository(resolved)
    event_publisher = publisher or PubSubEventPublisher(
        resolved.google_cloud_project or "",
        resolved.pubsub_change_topic,
        manage_resources=resolved.pubsub_manage_resources,
    )
    verifier = WebhookSignatureVerifier(resolved.event_gateway_webhook_secret)
    limiter = TenantEventRateLimiter(resolved.event_rate_limit_per_minute)
    change_status_base_url = resolved.control_api_base_url.rstrip("/")
    now = clock or (lambda: datetime.now(UTC))
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await _run_sync(event_publisher.ensure_ready)
        yield

    app = FastAPI(
        title="Enterprise ChangeOps Event Gateway",
        version="0.6.0",
        description="Authenticated transactional inbox and Pub/Sub publication boundary.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(EventGatewayError)
    async def gateway_error(request: Request, error: EventGatewayError) -> JSONResponse:
        return _problem(request, error)

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, _: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION",
                "detail": "Request validation failed.",
                "request_id": request.state.request_id,
            },
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(service="event-gateway", status="ok")

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        try:
            await _run_sync(inbox.check_ready)
            await _run_sync(event_publisher.check_ready)
        except Exception as error:
            raise EventDependencyError from error
        return HealthResponse(service="event-gateway", status="ready")

    @app.post(
        "/v1/events/change",
        response_model=EventAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["events"],
    )
    async def ingest_change(
        request: Request,
        signature: Annotated[str | None, Header(alias="X-ChangeOps-Signature")] = None,
    ) -> EventAcceptedResponse:
        body = await request.body()
        if len(body) > resolved.event_max_request_bytes:
            return JSONResponse(  # type: ignore[return-value]
                status_code=413,
                content={
                    "code": "REQUEST_TOO_LARGE",
                    "detail": "Change event request exceeds the configured size limit.",
                    "request_id": request.state.request_id,
                },
            )
        verifier.verify(body, signature)
        try:
            event = ChangeEvent.model_validate_json(body)
        except ValidationError as error:
            raise EventGatewayError(
                code="VALIDATION",
                detail="Change event schema validation failed.",
                status_code=422,
            ) from error
        timestamp = now()
        limiter.acquire(event.tenant_id, timestamp)
        change_id = derive_change_id(event)
        try:
            accepted = await _run_sync(
                inbox.accept,
                event=event,
                change_id=change_id,
                now=timestamp,
            )
            if accepted.record.status is InboxStatus.PUBLISHED:
                return EventAcceptedResponse(
                    event_id=event.event_id,
                    change_id=change_id,
                    status=accepted.record.status,
                    status_url=f"{change_status_base_url}/v1/changes/{change_id}",
                    replayed=True,
                )
            reservation = await _run_sync(
                inbox.reserve_publish,
                tenant_id=event.tenant_id,
                key=accepted.record.event_key,
                now=timestamp,
            )
            if reservation is None:
                return EventAcceptedResponse(
                    event_id=event.event_id,
                    change_id=change_id,
                    status=InboxStatus.PUBLISHING,
                    status_url=f"{change_status_base_url}/v1/changes/{change_id}",
                    replayed=True,
                )
            try:
                message_id = await _run_sync(event_publisher.publish, event, change_id)
            except Exception as error:
                await _run_sync(
                    inbox.mark_publish_failed,
                    tenant_id=event.tenant_id,
                    key=reservation.event_key,
                    expected_version=reservation.version,
                    error_code="PUBSUB_PUBLISH_FAILED",
                    now=now(),
                )
                raise EventDependencyError("PUBSUB_PUBLISH_FAILED") from error
            published = await _run_sync(
                inbox.mark_published,
                tenant_id=event.tenant_id,
                key=reservation.event_key,
                expected_version=reservation.version,
                message_id=message_id,
                now=now(),
            )
        except EventGatewayError:
            raise
        except Exception as error:
            raise EventDependencyError from error
        return EventAcceptedResponse(
            event_id=event.event_id,
            change_id=change_id,
            status=published.status,
            status_url=f"{change_status_base_url}/v1/changes/{change_id}",
            replayed=accepted.replayed,
        )

    return app
