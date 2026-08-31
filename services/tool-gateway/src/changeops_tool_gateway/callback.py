"""Approval decision callbacks for the durable workflow coordinator."""

from __future__ import annotations

from typing import Protocol

import httpx
from changeops_core import (
    NoopServiceAuthProvider,
    ServiceAuthenticationError,
    ServiceAuthProvider,
)

from changeops_tool_gateway.errors import ApprovalCallbackDeliveryError
from changeops_tool_gateway.models import ApprovalRequestRecord


class ApprovalCallbackNotifier(Protocol):
    async def notify(self, record: ApprovalRequestRecord) -> None: ...


class NoopApprovalCallbackNotifier:
    async def notify(self, record: ApprovalRequestRecord) -> None:
        del record


class HttpApprovalCallbackNotifier:
    def __init__(
        self,
        endpoint: str,
        *,
        secret: str,
        client: httpx.AsyncClient | None = None,
        service_auth: ServiceAuthProvider | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._secret = secret
        self._client = client
        self._service_auth = service_auth or NoopServiceAuthProvider()

    async def notify(self, record: ApprovalRequestRecord) -> None:
        if record.decided_at is None:
            raise ValueError("Only final approval decisions can trigger a callback.")
        client = self._client or httpx.AsyncClient(timeout=30)
        close_client = self._client is None
        try:
            platform_headers = await self._service_auth.headers(self._endpoint)
            response = await client.post(
                self._endpoint,
                headers={
                    "X-Workflow-Callback-Secret": self._secret,
                    **platform_headers,
                },
                json={
                    "tenant_id": record.tenant_id,
                    "change_id": record.change_id,
                    "approval_id": record.approval_id,
                    "plan_hash": record.plan_hash,
                    "plan_version": record.plan_version,
                    "status": record.status.value,
                    "decided_at": record.decided_at.isoformat(),
                },
            )
            if response.status_code >= 400:
                raise ApprovalCallbackDeliveryError
        except ApprovalCallbackDeliveryError:
            raise
        except (httpx.HTTPError, OSError, ServiceAuthenticationError, ValueError) as error:
            raise ApprovalCallbackDeliveryError from error
        finally:
            if close_client:
                await client.aclose()
