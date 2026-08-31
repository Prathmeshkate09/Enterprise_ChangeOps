"""Durable workflow service and authenticated approval callback boundary."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from changeops_core import (
    PersistenceBackend,
    ServiceAuthProvider,
    Settings,
    build_service_auth_provider,
    configure_logging,
    get_settings,
)
from changeops_persistence import (
    ChangeStateRepository,
    FirestoreChangeStateRepository,
    InMemoryChangeStateRepository,
)
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from changeops_workflow_coordinator.clients import FleetClient, GatewayClient, SandboxClient
from changeops_workflow_coordinator.engine import WorkflowEngine
from changeops_workflow_coordinator.errors import (
    CallbackAuthenticationError,
    WorkflowApiError,
    WorkflowPermanentError,
    WorkflowTransientError,
)
from changeops_workflow_coordinator.firestore_repository import FirestoreWorkflowRepository
from changeops_workflow_coordinator.models import (
    ApprovalCallbackRequest,
    DeadLetterListResponse,
    HealthResponse,
    WorkflowExecutionRecord,
)
from changeops_workflow_coordinator.repository import (
    InMemoryWorkflowRepository,
    WorkflowRepository,
)
from changeops_workflow_coordinator.retry import RetryPolicy
from changeops_workflow_coordinator.subscriber import (
    PubSubWorkflowSubscriber,
    WorkflowSubscriber,
)


def _change_repository(settings: Settings) -> ChangeStateRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryChangeStateRepository()
    if settings.google_cloud_project is None:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore workflows.")
    return FirestoreChangeStateRepository.from_project(
        settings.google_cloud_project, settings.firestore_database
    )


def _workflow_repository(settings: Settings) -> WorkflowRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryWorkflowRepository()
    if settings.google_cloud_project is None:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore workflows.")
    return FirestoreWorkflowRepository.from_project(
        settings.google_cloud_project, settings.firestore_database
    )


def create_app(
    *,
    settings: Settings | None = None,
    workflow_repository: WorkflowRepository | None = None,
    change_repository: ChangeStateRepository | None = None,
    engine: WorkflowEngine | None = None,
    subscriber: WorkflowSubscriber | None = None,
    service_auth_provider: ServiceAuthProvider | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    if resolved.workflow_callback_secret is None:
        raise ValueError("WORKFLOW_CALLBACK_SECRET is required.")
    workflows = workflow_repository or _workflow_repository(resolved)
    changes = change_repository or _change_repository(resolved)
    service_auth = service_auth_provider or build_service_auth_provider(resolved)
    if engine is None:
        if resolved.tool_gateway_auth_secret is None or resolved.auth_audience is None:
            raise ValueError("TOOL_GATEWAY_AUTH_SECRET and AUTH_AUDIENCE are required.")
        engine = WorkflowEngine(
            workflows=workflows,
            changes=changes,
            fleet=FleetClient(resolved.agent_fleet_base_url, service_auth=service_auth),
            gateway=GatewayClient(
                resolved.tool_gateway_base_url,
                identity_secret=resolved.tool_gateway_auth_secret,
                audience=resolved.auth_audience,
                service_auth=service_auth,
            ),
            sandboxes=SandboxClient(
                {
                    "crm": resolved.crm_base_url,
                    "analytics": resolved.analytics_base_url,
                    "support": resolved.support_base_url,
                },
                service_auth=service_auth,
            ),
            retry_policy=RetryPolicy(
                maximum_attempts=resolved.workflow_max_attempts,
                base_delay_seconds=resolved.workflow_retry_base_seconds,
            ),
        )
    if subscriber is None:
        if resolved.google_cloud_project is None:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Pub/Sub processing.")
        subscriber = PubSubWorkflowSubscriber(
            project=resolved.google_cloud_project,
            topic_id=resolved.pubsub_change_topic,
            subscription_id=resolved.pubsub_change_subscription,
            dead_letter_topic_id=resolved.pubsub_dead_letter_topic,
            dead_letter_subscription_id=resolved.pubsub_dead_letter_subscription,
            engine=engine,
            manage_resources=resolved.pubsub_manage_resources,
        )
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(subscriber.ensure_ready)
        subscriber.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            await asyncio.to_thread(subscriber.stop)

    app = FastAPI(
        title="Enterprise ChangeOps Workflow Coordinator",
        version="0.6.0",
        description="Durable approval, DAG, retry, verification, and rollback coordination.",
        lifespan=lifespan,
    )

    @app.exception_handler(WorkflowApiError)
    async def api_error(request: Request, error: WorkflowApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": error.code,
                "detail": error.detail,
                "request_id": request.headers.get("X-Request-ID", "unknown"),
            },
        )

    @app.exception_handler(WorkflowPermanentError)
    async def permanent_error(request: Request, error: WorkflowPermanentError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "code": error.code,
                "detail": error.detail,
                "request_id": request.headers.get("X-Request-ID", "unknown"),
            },
        )

    @app.exception_handler(WorkflowTransientError)
    async def transient_error(request: Request, error: WorkflowTransientError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": error.code,
                "detail": error.detail,
                "request_id": request.headers.get("X-Request-ID", "unknown"),
            },
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(service="workflow-coordinator", status="ok")

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        await asyncio.to_thread(workflows.check_ready)
        await asyncio.to_thread(changes.check_ready)
        await asyncio.to_thread(subscriber.check_ready)
        return HealthResponse(service="workflow-coordinator", status="ready")

    @app.get(
        "/v1/workflows/{workflow_execution_id}",
        response_model=WorkflowExecutionRecord,
        tags=["workflows"],
    )
    async def get_workflow(
        workflow_execution_id: str,
        change_id: Annotated[str, Query(min_length=1, max_length=512)],
        tenant_id: Annotated[str, Header(alias="X-Tenant-ID", min_length=1, max_length=128)],
    ) -> WorkflowExecutionRecord:
        return await asyncio.to_thread(workflows.get, tenant_id, change_id, workflow_execution_id)

    @app.get("/v1/dead-letters", response_model=DeadLetterListResponse, tags=["workflows"])
    async def dead_letters(
        tenant_id: Annotated[str, Header(alias="X-Tenant-ID", min_length=1, max_length=128)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> DeadLetterListResponse:
        items = await asyncio.to_thread(workflows.list_dead_letters, tenant_id, limit=limit)
        return DeadLetterListResponse(items=items, count=len(items))

    @app.post(
        "/internal/v1/approval-callbacks",
        response_model=WorkflowExecutionRecord,
        tags=["internal"],
    )
    async def approval_callback(
        body: ApprovalCallbackRequest,
        callback_secret: Annotated[str | None, Header(alias="X-Workflow-Callback-Secret")] = None,
    ) -> WorkflowExecutionRecord:
        if callback_secret is None or not hmac.compare_digest(
            callback_secret, resolved.workflow_callback_secret or ""
        ):
            raise CallbackAuthenticationError
        return await engine.resume_approval(body)

    return app
