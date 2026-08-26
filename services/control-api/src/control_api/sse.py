"""Resumable Server-Sent Event encoding and polling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import partial

from changeops_contracts import AuditEvent
from changeops_persistence import ChangeStateRepository
from fastapi import Request
from starlette.concurrency import run_in_threadpool


def encode_audit_event(event: AuditEvent) -> str:
    return f"id: {event.audit_event_id}\nevent: audit\ndata: {event.model_dump_json()}\n\n"


async def audit_event_stream(
    *,
    request: Request,
    repository: ChangeStateRepository,
    tenant_id: str,
    change_id: str,
    initial_events: tuple[AuditEvent, ...],
    after_event_id: str | None,
    follow: bool,
) -> AsyncIterator[str]:
    cursor = after_event_id
    pending = initial_events
    while True:
        for event in pending:
            yield encode_audit_event(event)
            cursor = event.audit_event_id
        if not follow or await request.is_disconnected():
            return
        if not pending:
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.75)
        pending = await run_in_threadpool(
            partial(
                repository.list_audit_after,
                tenant_id,
                change_id,
                after_event_id=cursor,
                limit=100,
            )
        )
