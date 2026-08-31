"""Typed HTTP adapters for the three bounded sandbox mutation tools."""

from __future__ import annotations

from typing import ClassVar, Protocol, cast

import httpx
from changeops_contracts import ToolIntent
from changeops_core import (
    NoopServiceAuthProvider,
    ServiceAuthenticationError,
    ServiceAuthProvider,
)
from changeops_policy_engine import ToolRegistration
from pydantic import JsonValue, ValidationError

from changeops_tool_gateway.errors import GatewayValidationError, ToolAdapterError
from changeops_tool_gateway.models import FieldPatchArguments, PatchExecutionOutput


class ToolExecutor(Protocol):
    def validate_arguments(self, intent: ToolIntent) -> FieldPatchArguments:
        """Validate arguments against the selected registered tool schema."""

    async def execute(
        self,
        *,
        intent: ToolIntent,
        registration: ToolRegistration,
        arguments: FieldPatchArguments,
        request_id: str,
    ) -> dict[str, JsonValue]:
        """Execute and validate one typed tool adapter call."""


class HttpToolExecutor:
    _SERVICE_BY_TOOL: ClassVar[dict[str, str]] = {
        "crm.update_field_mapping": "crm",
        "analytics.update_field_mapping": "analytics",
        "support.update_lookup_field": "support",
    }

    def __init__(
        self,
        base_urls: dict[str, str],
        *,
        client: httpx.AsyncClient | None = None,
        service_auth: ServiceAuthProvider | None = None,
    ) -> None:
        if set(base_urls) != {"crm", "analytics", "support"}:
            raise ValueError("Tool executor requires exactly the three sandbox service URLs.")
        self._base_urls = {name: value.rstrip("/") for name, value in base_urls.items()}
        self._client = client
        self._service_auth = service_auth or NoopServiceAuthProvider()

    def validate_arguments(self, intent: ToolIntent) -> FieldPatchArguments:
        if intent.tool_name not in self._SERVICE_BY_TOOL:
            raise GatewayValidationError("No argument schema is registered for this tool.")
        try:
            return FieldPatchArguments.model_validate(intent.arguments)
        except ValidationError as error:
            raise GatewayValidationError from error

    async def execute(
        self,
        *,
        intent: ToolIntent,
        registration: ToolRegistration,
        arguments: FieldPatchArguments,
        request_id: str,
    ) -> dict[str, JsonValue]:
        service = self._SERVICE_BY_TOOL.get(registration.tool_name)
        if service is None:
            raise GatewayValidationError("Tool has no bounded execution adapter.")
        payload = {
            **arguments.model_dump(mode="json"),
            "idempotency_key": intent.idempotency_key,
            "change_id": intent.change_id,
            "plan_hash": intent.plan_hash,
        }
        client = self._client or httpx.AsyncClient(timeout=registration.timeout_seconds)
        close_client = self._client is None
        try:
            base_url = self._base_urls[service]
            platform_headers = await self._service_auth.headers(base_url)
            response = await client.post(
                f"{base_url}/v1/patches/apply",
                headers={
                    "X-Tenant-ID": intent.tenant_id,
                    "X-Request-ID": request_id,
                    **platform_headers,
                },
                json=payload,
                timeout=registration.timeout_seconds,
            )
            if response.status_code >= 400:
                transient = response.status_code >= 500 or response.status_code == 429
                raise ToolAdapterError(
                    code="TRANSIENT" if transient else "PERMANENT",
                    detail="The registered sandbox tool rejected the request.",
                    transient=transient,
                )
            result = PatchExecutionOutput.model_validate(response.json())
            if (
                result.before != arguments.old_field
                or result.after != arguments.new_field
                or result.idempotency_key != intent.idempotency_key
            ):
                raise ToolAdapterError(
                    code="VALIDATION",
                    detail="The registered sandbox tool returned an out-of-scope result.",
                    transient=False,
                )
            return cast(dict[str, JsonValue], result.model_dump(mode="json"))
        except ToolAdapterError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, ServiceAuthenticationError) as error:
            raise ToolAdapterError(
                code="TRANSIENT",
                detail="The registered sandbox tool is temporarily unavailable.",
                transient=True,
            ) from error
        except (ValueError, ValidationError) as error:
            raise ToolAdapterError(
                code="VALIDATION",
                detail="The registered sandbox tool returned an invalid response.",
                transient=False,
            ) from error
        finally:
            if close_client:
                await client.aclose()
