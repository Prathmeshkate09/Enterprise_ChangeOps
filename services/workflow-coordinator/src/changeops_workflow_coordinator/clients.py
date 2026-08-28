"""Typed clients for the bounded fleet, gateway, and sandbox services."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, ClassVar, Literal, cast

import httpx
from changeops_contracts import (
    ChangeEnvironment,
    ChangeEvent,
    FleetAnalysisRequest,
    FleetAnalysisResult,
    RemediationPlan,
    RemediationStep,
    ToolIntent,
    sha256_digest,
)
from changeops_policy_engine import IdentityKind
from changeops_tool_gateway.identity import HmacIdentityVerifier
from changeops_tool_gateway.models import (
    ApprovalCreateRequest,
    ApprovalRequestRecord,
    GatewayExecutionRequest,
    GatewayExecutionResult,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class DependencyCallError(RuntimeError):
    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


def _response_error(response: httpx.Response) -> DependencyCallError:
    code = f"HTTP_{response.status_code}"
    try:
        body = response.json()
        if isinstance(body, dict):
            candidate = body.get("code")
            if candidate is None and isinstance(body.get("error"), dict):
                candidate = body["error"].get("code")
            if isinstance(candidate, str) and candidate:
                code = candidate
    except ValueError:
        pass
    return DependencyCallError(
        code,
        transient=response.status_code == 429 or response.status_code >= 500,
    )


class FleetClient:
    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def analyze(
        self, *, change_id: str, event: ChangeEvent, request_id: str
    ) -> FleetAnalysisResult:
        client = self._client or httpx.AsyncClient(timeout=60)
        close_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/v1/analyses",
                headers={"X-Tenant-ID": event.tenant_id, "X-Request-ID": request_id},
                json=FleetAnalysisRequest(change_id=change_id, event=event).model_dump(mode="json"),
            )
            if response.status_code >= 400:
                raise _response_error(response)
            return FleetAnalysisResult.model_validate(response.json())
        except DependencyCallError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise DependencyCallError("FLEET_UNAVAILABLE", transient=True) from error
        except (ValueError, ValidationError) as error:
            raise DependencyCallError("FLEET_INVALID_RESPONSE", transient=False) from error
        finally:
            if close_client:
                await client.aclose()


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        *,
        identity_secret: str,
        audience: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._issuer = HmacIdentityVerifier(identity_secret, audience)
        self._client = client

    def _token(self, *, subject: str, tenant_id: str, kind: IdentityKind) -> str:
        return self._issuer.issue(
            subject=subject,
            tenant_id=tenant_id,
            kind=kind,
            lifetime=timedelta(minutes=10),
        )

    async def create_approval(
        self,
        *,
        approval_id: str,
        plan: RemediationPlan,
        expires_at: datetime,
        request_id: str,
    ) -> ApprovalRequestRecord:
        body = ApprovalCreateRequest(
            approval_id=approval_id,
            plan=plan,
            environment=ChangeEnvironment.SANDBOX,
            scope=tuple(step.step_id for step in plan.steps),
            expires_at=expires_at,
        )
        return await self._request(
            method="POST",
            path="/v1/approvals",
            token=self._token(
                subject="workflow-coordinator",
                tenant_id=plan.tenant_id,
                kind=IdentityKind.SERVICE,
            ),
            request_id=request_id,
            payload=body.model_dump(mode="json"),
            output_type=ApprovalRequestRecord,
        )

    async def execute(
        self,
        *,
        workflow_execution_id: str,
        plan: RemediationPlan,
        step: RemediationStep,
        approval_id: str,
        requested_at: datetime,
        request_id: str,
    ) -> GatewayExecutionResult:
        intent = ToolIntent(
            schema_version="1.0",
            intent_id=f"intent_{workflow_execution_id}_{step.step_id}",
            tenant_id=plan.tenant_id,
            change_id=plan.change_id,
            workflow_execution_id=workflow_execution_id,
            plan_id=plan.plan_id,
            plan_hash=sha256_digest(plan),
            step_id=step.step_id,
            agent_identity=step.agent_id,
            tool_name=step.tool_name,
            action="update",
            resource=step.resource,
            arguments=step.arguments,
            reason="Execute the exact approved durable workflow step.",
            evidence_refs=plan.evidence_refs,
            idempotency_key=step.idempotency_key,
            requested_at=requested_at,
        )
        body = GatewayExecutionRequest(intent=intent, approval_id=approval_id)
        return await self._request(
            method="POST",
            path="/internal/v1/tool-intents/evaluate-and-execute",
            token=self._token(
                subject=step.agent_id,
                tenant_id=plan.tenant_id,
                kind=IdentityKind.AGENT,
            ),
            request_id=request_id,
            payload=body.model_dump(mode="json"),
            output_type=GatewayExecutionResult,
        )

    async def _request[Output: BaseModel](
        self,
        *,
        method: Literal["GET", "POST"],
        path: str,
        token: str,
        request_id: str,
        payload: dict[str, JsonValue] | None,
        output_type: type[Output],
    ) -> Output:
        client = self._client or httpx.AsyncClient(timeout=30)
        close_client = self._client is None
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                },
                json=payload,
            )
            if response.status_code >= 400:
                raise _response_error(response)
            return output_type.model_validate(response.json())
        except DependencyCallError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise DependencyCallError("TOOL_GATEWAY_UNAVAILABLE", transient=True) from error
        except (ValueError, ValidationError) as error:
            raise DependencyCallError("TOOL_GATEWAY_INVALID_RESPONSE", transient=False) from error
        finally:
            if close_client:
                await client.aclose()


class SandboxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SnapshotRecord(SandboxModel):
    snapshot_id: NonEmptyStr
    tenant_id: NonEmptyStr
    system_id: NonEmptyStr
    configuration: dict[str, JsonValue]
    configuration_hash: Sha256Digest
    created_at: AwareDatetime


class RestoreResult(SandboxModel):
    system_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    configuration_hash: Sha256Digest
    restored: bool


class VerificationCheck(SandboxModel):
    name: NonEmptyStr
    passed: bool
    detail: NonEmptyStr


class VerificationResult(SandboxModel):
    system_id: NonEmptyStr
    passed: bool
    checks: tuple[VerificationCheck, ...]


class AnalyticsVerificationResult(VerificationResult):
    baseline_row_count: int
    observed_row_count: int
    null_rate: float


class SandboxClient:
    _SERVICE_BY_TOOL: ClassVar[dict[str, str]] = {
        "crm.update_field_mapping": "crm",
        "analytics.update_field_mapping": "analytics",
        "support.update_lookup_field": "support",
    }
    _VERIFICATION_PATHS: ClassVar[dict[str, str]] = {
        "crm": "/v1/verification/synchronization",
        "analytics": "/v1/verification/data-quality",
        "support": "/v1/verification/lookup",
    }

    def __init__(
        self, base_urls: dict[str, str], *, client: httpx.AsyncClient | None = None
    ) -> None:
        if set(base_urls) != {"crm", "analytics", "support"}:
            raise ValueError("Sandbox client requires exactly CRM, Analytics, and Support URLs.")
        self._base_urls = {name: url.rstrip("/") for name, url in base_urls.items()}
        self._client = client

    def system_for_step(self, step: RemediationStep) -> Literal["crm", "analytics", "support"]:
        system = self._SERVICE_BY_TOOL.get(step.tool_name)
        if system not in {"crm", "analytics", "support"}:
            raise DependencyCallError("UNSUPPORTED_PLAN_TOOL", transient=False)
        return cast(Literal["crm", "analytics", "support"], system)

    async def snapshot(self, *, system: str, tenant_id: str, request_id: str) -> SnapshotRecord:
        response = await self._call(
            method="POST",
            url=f"{self._base_urls[system]}/v1/snapshots",
            tenant_id=tenant_id,
            request_id=request_id,
        )
        try:
            return SnapshotRecord.model_validate(response.json())
        except ValidationError as error:
            raise DependencyCallError("SNAPSHOT_INVALID_RESPONSE", transient=False) from error

    async def restore(
        self, *, system: str, tenant_id: str, snapshot_id: str, request_id: str
    ) -> RestoreResult:
        response = await self._call(
            method="POST",
            url=f"{self._base_urls[system]}/v1/snapshots/{snapshot_id}/restore",
            tenant_id=tenant_id,
            request_id=request_id,
        )
        try:
            result = RestoreResult.model_validate(response.json())
        except ValidationError as error:
            raise DependencyCallError("RESTORE_INVALID_RESPONSE", transient=False) from error
        if not result.restored or result.snapshot_id != snapshot_id:
            raise DependencyCallError("RESTORE_NOT_CONFIRMED", transient=False)
        return result

    async def verify(
        self, *, system: str, tenant_id: str, expected_field: str, request_id: str
    ) -> VerificationResult:
        response = await self._call(
            method="POST",
            url=f"{self._base_urls[system]}{self._VERIFICATION_PATHS[system]}",
            tenant_id=tenant_id,
            request_id=request_id,
            payload={"expected_field": expected_field},
        )
        output_type: type[VerificationResult] = (
            AnalyticsVerificationResult if system == "analytics" else VerificationResult
        )
        try:
            return output_type.model_validate(response.json())
        except ValidationError as error:
            raise DependencyCallError("VERIFICATION_INVALID_RESPONSE", transient=False) from error

    async def configuration_hash(self, *, system: str, tenant_id: str, request_id: str) -> str:
        response = await self._call(
            method="GET",
            url=f"{self._base_urls[system]}/v1/configuration",
            tenant_id=tenant_id,
            request_id=request_id,
        )
        try:
            document = response.json()
        except ValueError as error:
            raise DependencyCallError("CONFIGURATION_INVALID_RESPONSE", transient=False) from error
        if not isinstance(document, dict):
            raise DependencyCallError("CONFIGURATION_INVALID_RESPONSE", transient=False)
        return sha256_digest(cast(dict[str, JsonValue], document))

    async def _call(
        self,
        *,
        method: Literal["GET", "POST"],
        url: str,
        tenant_id: str,
        request_id: str,
        payload: dict[str, JsonValue] | None = None,
    ) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=15)
        close_client = self._client is None
        try:
            response = await client.request(
                method,
                url,
                headers={"X-Tenant-ID": tenant_id, "X-Request-ID": request_id},
                json=payload,
            )
            if response.status_code >= 400:
                raise _response_error(response)
            return response
        except DependencyCallError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise DependencyCallError("SANDBOX_UNAVAILABLE", transient=True) from error
        finally:
            if close_client:
                await client.aclose()
