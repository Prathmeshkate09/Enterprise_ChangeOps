"""Versioned tenant-facing change and audit routes."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Annotated, ParamSpec, TypeVar

from changeops_contracts import ActorType, ChangeRecord, WorkflowState
from changeops_core import StateTransitionService
from changeops_persistence import ChangeAlreadyExistsError, ChangeStateRepository
from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from control_api.context import ActorId, TenantId
from control_api.demo import build_demo_change
from control_api.models import AuditListResponse, ChangeListResponse, TransitionRequest
from control_api.sse import audit_event_stream

P = ParamSpec("P")
R = TypeVar("R")


async def _run_sync(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    return await run_in_threadpool(partial(function, *args, **kwargs))


def build_router(repository: ChangeStateRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/changes", response_model=ChangeListResponse, tags=["changes"])
    async def list_changes(
        tenant_id: TenantId,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ChangeListResponse:
        items = await _run_sync(repository.list_changes, tenant_id, limit=limit)
        return ChangeListResponse(items=items, count=len(items))

    @router.get(
        "/v1/changes/{change_id}",
        response_model=ChangeRecord,
        tags=["changes"],
    )
    async def get_change(change_id: str, tenant_id: TenantId) -> ChangeRecord:
        return await _run_sync(repository.get, tenant_id, change_id)

    @router.get(
        "/v1/changes/{change_id}/audit",
        response_model=AuditListResponse,
        tags=["audit"],
    )
    async def list_change_audit(
        change_id: str,
        tenant_id: TenantId,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> AuditListResponse:
        items = await _run_sync(
            repository.list_audit_after,
            tenant_id,
            change_id,
            after_event_id=None,
            limit=limit,
        )
        return AuditListResponse(items=items, count=len(items))

    @router.get("/v1/audit", response_model=AuditListResponse, tags=["audit"])
    async def list_tenant_audit(
        tenant_id: TenantId,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> AuditListResponse:
        items = await _run_sync(repository.list_tenant_audit, tenant_id, limit=limit)
        return AuditListResponse(items=items, count=len(items))

    @router.get(
        "/v1/changes/{change_id}/stream",
        response_class=StreamingResponse,
        tags=["changes"],
    )
    async def stream_change(
        request: Request,
        change_id: str,
        tenant_id: TenantId,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        follow: Annotated[bool, Query()] = True,
    ) -> StreamingResponse:
        initial_events = await _run_sync(
            repository.list_audit_after,
            tenant_id,
            change_id,
            after_event_id=last_event_id,
            limit=100,
        )
        return StreamingResponse(
            audit_event_stream(
                request=request,
                repository=repository,
                tenant_id=tenant_id,
                change_id=change_id,
                initial_events=initial_events,
                after_event_id=last_event_id,
                follow=follow,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def transition(
        *,
        tenant_id: str,
        change_id: str,
        target: WorkflowState,
        mutation: TransitionRequest,
        actor_id: str,
    ) -> ChangeRecord:
        service = StateTransitionService(repository)
        await _run_sync(
            service.transition,
            tenant_id=tenant_id,
            change_id=change_id,
            target=target,
            expected_version=mutation.expected_version,
            trace_id=mutation.trace_id,
            actor_type=ActorType.USER,
            actor_id=actor_id,
        )
        return await _run_sync(repository.get, tenant_id, change_id)

    @router.post(
        "/v1/changes/{change_id}/cancel",
        response_model=ChangeRecord,
        tags=["changes"],
    )
    async def cancel_change(
        change_id: str,
        mutation: TransitionRequest,
        tenant_id: TenantId,
        actor_id: ActorId,
    ) -> ChangeRecord:
        return await transition(
            tenant_id=tenant_id,
            change_id=change_id,
            target=WorkflowState.CANCELLED,
            mutation=mutation,
            actor_id=actor_id,
        )

    @router.post(
        "/v1/changes/{change_id}/retry",
        response_model=ChangeRecord,
        tags=["changes"],
    )
    async def retry_change(
        change_id: str,
        mutation: TransitionRequest,
        tenant_id: TenantId,
        actor_id: ActorId,
    ) -> ChangeRecord:
        current = await _run_sync(repository.get, tenant_id, change_id)
        target = (
            WorkflowState.SCREENING
            if current.status in {WorkflowState.BLOCKED, WorkflowState.NEEDS_ATTENTION}
            else current.status
        )
        return await transition(
            tenant_id=tenant_id,
            change_id=change_id,
            target=target,
            mutation=mutation,
            actor_id=actor_id,
        )

    @router.post(
        "/v1/demo/events/api-breaking-change",
        response_model=ChangeRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def create_demo_change(response: Response, tenant_id: TenantId) -> ChangeRecord:
        change, audit = build_demo_change(tenant_id)
        try:
            await _run_sync(repository.add_with_audit, change, audit)
        except ChangeAlreadyExistsError:
            existing = await _run_sync(repository.get, tenant_id, change.change_id)
            if existing.event_id != change.event_id:
                raise
            response.status_code = status.HTTP_200_OK
            return existing
        return await _run_sync(repository.get, tenant_id, change.change_id)

    return router
