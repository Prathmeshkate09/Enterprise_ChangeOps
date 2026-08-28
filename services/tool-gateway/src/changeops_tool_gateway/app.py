"""Authenticated approval and evaluate-and-execute HTTP boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated, Any, ParamSpec, TypeVar, cast
from uuid import uuid4

from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    PolicyDecision,
    PolicyEffect,
    RiskLevel,
    ToolIntent,
    UserRole,
    WorkflowState,
    calculate_plan_hash,
    sha256_digest,
)
from changeops_core import PersistenceBackend, Settings, configure_logging, get_logger, get_settings
from changeops_persistence import (
    ChangeNotFoundError,
    ChangeStateRepository,
    FirestoreChangeStateRepository,
    InMemoryChangeStateRepository,
    PersistenceError,
    TenantScopeViolationError,
)
from changeops_policy_engine import (
    IdentityKind,
    PolicyEngine,
    ToolRegistry,
    VerifiedIdentity,
    build_default_tool_registry,
)
from fastapi import Depends, FastAPI, Header, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from changeops_tool_gateway.callback import (
    ApprovalCallbackNotifier,
    HttpApprovalCallbackNotifier,
    NoopApprovalCallbackNotifier,
)
from changeops_tool_gateway.errors import (
    ApprovalRequiredError,
    AuthenticationError,
    AuthorizationError,
    GatewayConflictError,
    GatewayError,
    GatewayNotFoundError,
    GatewayValidationError,
    PolicyDeniedError,
    ToolAdapterError,
)
from changeops_tool_gateway.executor import HttpToolExecutor, ToolExecutor
from changeops_tool_gateway.firestore_repository import FirestoreGovernanceRepository
from changeops_tool_gateway.identity import HmacIdentityVerifier, IdentityVerifier
from changeops_tool_gateway.models import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalListResponse,
    ApprovalRequestRecord,
    ApprovalRequestStatus,
    AuditListResponse,
    GatewayExecutionRequest,
    GatewayExecutionResult,
    HealthResponse,
    ToolExecutionStatus,
)
from changeops_tool_gateway.quota import ToolQuotaManager
from changeops_tool_gateway.repository import GovernanceRepository, InMemoryGovernanceRepository

P = ParamSpec("P")
R = TypeVar("R")


async def _run_sync(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    return await run_in_threadpool(partial(function, *args, **kwargs))


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


def _problem(request: Request, error: GatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "type": f"https://changeops.example/problems/{error.code.lower().replace('_', '-')}",
            "title": error.title,
            "status": error.status_code,
            "code": error.code,
            "detail": error.detail,
            "request_id": request.state.request_id,
        },
        headers={"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None,
    )


def _actor_type(identity: VerifiedIdentity) -> ActorType:
    return {
        IdentityKind.AGENT: ActorType.AGENT,
        IdentityKind.SERVICE: ActorType.SERVICE,
        IdentityKind.USER: ActorType.USER,
    }[identity.kind]


def _semantic_input_hash(intent: ToolIntent) -> str:
    return sha256_digest(
        {
            "tenant_id": intent.tenant_id,
            "change_id": intent.change_id,
            "workflow_execution_id": intent.workflow_execution_id,
            "plan_id": intent.plan_id,
            "plan_hash": intent.plan_hash,
            "step_id": intent.step_id,
            "agent_identity": intent.agent_identity,
            "tool_name": intent.tool_name,
            "action": intent.action,
            "resource": intent.resource,
            "arguments": intent.arguments,
            "idempotency_key": intent.idempotency_key,
        }
    )


def _tool_audit(
    *,
    identity: VerifiedIdentity,
    intent: ToolIntent,
    event_type: str,
    decision: PolicyDecision,
    input_hash: str,
    output: BaseModel | dict[str, Any],
    status_value: AuditStatus,
    summary: str,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        audit_event_id=f"audit_{uuid4().hex}",
        tenant_id=intent.tenant_id,
        change_id=intent.change_id,
        trace_id=intent.workflow_execution_id,
        event_type=event_type,
        actor_type=_actor_type(identity),
        actor_id=identity.subject,
        resource=intent.resource,
        action=intent.action,
        decision_id=decision.decision_id,
        input_hash=input_hash,
        output_hash=sha256_digest(output),
        status=status_value,
        redacted_summary=summary,
        created_at=now,
    )


def _approval_audit(
    *,
    identity: VerifiedIdentity,
    record: ApprovalRequestRecord,
    event_type: str,
    summary: str,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        audit_event_id=f"audit_{uuid4().hex}",
        tenant_id=record.tenant_id,
        change_id=record.change_id,
        trace_id=f"approval:{record.approval_id}",
        event_type=event_type,
        actor_type=_actor_type(identity),
        actor_id=identity.subject,
        resource=f"approvals/{record.approval_id}",
        action=event_type.lower(),
        input_hash=sha256_digest(
            {
                "approval_id": record.approval_id,
                "plan_hash": record.plan_hash,
                "scope": record.scope,
            }
        ),
        output_hash=sha256_digest(record),
        status=AuditStatus.SUCCESS,
        redacted_summary=summary,
        created_at=now,
    )


def _require_roles(identity: VerifiedIdentity, roles: set[UserRole]) -> None:
    if identity.kind is not IdentityKind.USER or not (set(identity.roles) & roles):
        raise AuthorizationError


async def _authenticate_identity(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> VerifiedIdentity:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthenticationError
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError
    verifier = cast(IdentityVerifier, request.app.state.identity_verifier)
    return verifier.verify(token)


def _build_change_repository(settings: Settings) -> ChangeStateRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryChangeStateRepository()
    if not settings.google_cloud_project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for the Firestore backend.")
    return FirestoreChangeStateRepository.from_project(
        settings.google_cloud_project,
        settings.firestore_database,
    )


def _build_governance_repository(settings: Settings) -> GovernanceRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryGovernanceRepository()
    if not settings.google_cloud_project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for the Firestore backend.")
    return FirestoreGovernanceRepository.from_project(
        settings.google_cloud_project,
        settings.firestore_database,
    )


def create_app(
    *,
    settings: Settings | None = None,
    identity_verifier: IdentityVerifier | None = None,
    governance_repository: GovernanceRepository | None = None,
    change_repository: ChangeStateRepository | None = None,
    tool_registry: ToolRegistry | None = None,
    policy_engine: PolicyEngine | None = None,
    tool_executor: ToolExecutor | None = None,
    quota_manager: ToolQuotaManager | None = None,
    approval_callback_notifier: ApprovalCallbackNotifier | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    now = clock or (lambda: datetime.now(UTC))
    if identity_verifier is None:
        if resolved.tool_gateway_auth_secret is None or resolved.auth_audience is None:
            raise ValueError("TOOL_GATEWAY_AUTH_SECRET and AUTH_AUDIENCE are required.")
        identity_verifier = HmacIdentityVerifier(
            resolved.tool_gateway_auth_secret,
            resolved.auth_audience,
            clock=now,
        )
    governance = governance_repository or _build_governance_repository(resolved)
    changes = change_repository or _build_change_repository(resolved)
    registry = tool_registry or build_default_tool_registry()
    policy = policy_engine or PolicyEngine()
    executor = tool_executor or HttpToolExecutor(
        {
            "crm": resolved.crm_base_url,
            "analytics": resolved.analytics_base_url,
            "support": resolved.support_base_url,
        }
    )
    quotas = quota_manager or ToolQuotaManager()
    if approval_callback_notifier is not None:
        callback_notifier = approval_callback_notifier
    elif resolved.workflow_callback_url is not None:
        if resolved.workflow_callback_secret is None:
            raise ValueError(
                "WORKFLOW_CALLBACK_SECRET is required when WORKFLOW_CALLBACK_URL is set."
            )
        callback_notifier = HttpApprovalCallbackNotifier(
            resolved.workflow_callback_url,
            secret=resolved.workflow_callback_secret,
        )
    else:
        callback_notifier = NoopApprovalCallbackNotifier()
    configure_logging(resolved.log_level)
    logger = get_logger("tool-gateway")

    app = FastAPI(
        title="Enterprise ChangeOps Tool Gateway",
        version="0.5.0",
        description="Authenticated exact-plan approval and typed sandbox execution boundary.",
    )
    app.state.identity_verifier = identity_verifier
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, error: GatewayError) -> JSONResponse:
        return _problem(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "type": "https://changeops.example/problems/validation",
                "title": "Validation failed",
                "status": 422,
                "code": "VALIDATION",
                "detail": "Request validation failed.",
                "request_id": request.state.request_id,
                "errors": [
                    {
                        "type": item.get("type"),
                        "loc": item.get("loc"),
                        "msg": item.get("msg"),
                    }
                    for item in error.errors()
                ],
            },
        )

    @app.exception_handler(ChangeNotFoundError)
    @app.exception_handler(TenantScopeViolationError)
    async def change_not_found_handler(request: Request, _: Exception) -> JSONResponse:
        return _problem(request, GatewayNotFoundError("change"))

    @app.exception_handler(PersistenceError)
    async def persistence_error_handler(request: Request, _: PersistenceError) -> JSONResponse:
        logger.exception("tool_gateway_persistence_failure", request_id=request.state.request_id)
        return _problem(
            request,
            GatewayError(
                code="PERSISTENCE_UNAVAILABLE",
                title="Persistence unavailable",
                detail="Authoritative governance persistence is unavailable.",
                status_code=503,
            ),
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(
            service="tool-gateway", status="ok", environment=resolved.app_env.value
        )

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        await _run_sync(governance.check_ready)
        await _run_sync(changes.check_ready)
        return HealthResponse(
            service="tool-gateway", status="ready", environment=resolved.app_env.value
        )

    @app.get("/v1/tools", tags=["registry"])
    async def tools(
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> tuple[Any, ...]:
        del identity
        return registry.list()

    @app.post(
        "/v1/approvals",
        response_model=ApprovalRequestRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["approvals"],
    )
    async def create_approval(
        body: ApprovalCreateRequest,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> ApprovalRequestRecord:
        if identity.kind not in {IdentityKind.AGENT, IdentityKind.SERVICE}:
            raise AuthorizationError(
                "Only a workflow service or registered agent may request approval."
            )
        if body.plan.tenant_id != identity.tenant_id:
            raise AuthorizationError
        created_at = now()
        if body.expires_at <= created_at or body.expires_at > created_at + timedelta(hours=1):
            raise GatewayValidationError("Approval expiration must be within the next hour.")
        change = await _run_sync(changes.get, identity.tenant_id, body.plan.change_id)
        plan_hash = calculate_plan_hash(body.plan)
        if change.status is not WorkflowState.AWAITING_APPROVAL:
            raise GatewayConflictError("Change is not awaiting approval.")
        if (
            change.plan_version != body.plan.version
            or change.plan_hash != plan_hash
            or change.environment != body.environment
        ):
            raise GatewayConflictError(
                "Approval request does not match the authoritative change plan."
            )
        record = ApprovalRequestRecord(
            approval_id=body.approval_id,
            tenant_id=body.plan.tenant_id,
            change_id=body.plan.change_id,
            plan_id=body.plan.plan_id,
            plan_hash=plan_hash,
            plan_version=body.plan.version,
            environment=body.environment,
            scope=body.scope,
            status=ApprovalRequestStatus.PENDING,
            requested_by=identity.subject,
            requested_at=created_at,
            expires_at=body.expires_at,
            version=1,
        )
        stored = await _run_sync(governance.create_approval_request, record=record, plan=body.plan)
        if stored.requested_at == created_at:
            await _run_sync(
                governance.record_audit,
                _approval_audit(
                    identity=identity,
                    record=stored,
                    event_type="APPROVAL_REQUESTED",
                    summary="Exact-plan sandbox approval requested.",
                    now=created_at,
                ),
            )
        return stored

    @app.get("/v1/approvals", response_model=ApprovalListResponse, tags=["approvals"])
    async def list_approvals(
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ApprovalListResponse:
        _require_roles(
            identity,
            {UserRole.APPROVER, UserRole.AUDITOR, UserRole.PLATFORM_ADMIN},
        )
        items = await _run_sync(governance.list_approval_requests, identity.tenant_id, limit=limit)
        return ApprovalListResponse(items=items, count=len(items))

    @app.get(
        "/v1/approvals/{approval_id}",
        response_model=ApprovalRequestRecord,
        tags=["approvals"],
    )
    async def get_approval(
        approval_id: str,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> ApprovalRequestRecord:
        _require_roles(
            identity,
            {UserRole.APPROVER, UserRole.AUDITOR, UserRole.PLATFORM_ADMIN},
        )
        return await _run_sync(governance.get_approval_request, identity.tenant_id, approval_id)

    async def decide_approval(
        *,
        approval_id: str,
        body: ApprovalDecisionRequest,
        identity: VerifiedIdentity,
        target: ApprovalRequestStatus,
    ) -> ApprovalRequestRecord:
        _require_roles(identity, {UserRole.APPROVER, UserRole.PLATFORM_ADMIN})
        timestamp = now()
        record = await _run_sync(
            governance.decide_approval,
            tenant_id=identity.tenant_id,
            approval_id=approval_id,
            target=target,
            expected_version=body.expected_version,
            decided_by=identity.subject,
            decided_by_roles=identity.roles,
            comment=body.comment,
            decided_at=timestamp,
        )
        event_type = {
            ApprovalRequestStatus.APPROVED: "APPROVAL_GRANTED",
            ApprovalRequestStatus.REJECTED: "APPROVAL_REJECTED",
            ApprovalRequestStatus.CHANGES_REQUESTED: "APPROVAL_CHANGES_REQUESTED",
        }[target]
        await _run_sync(
            governance.record_audit,
            _approval_audit(
                identity=identity,
                record=record,
                event_type=event_type,
                summary=f"Exact-plan sandbox approval decision: {target.value}.",
                now=timestamp,
            ),
        )
        await callback_notifier.notify(record)
        return record

    @app.post(
        "/v1/approvals/{approval_id}/approve",
        response_model=ApprovalRequestRecord,
        tags=["approvals"],
    )
    async def approve(
        approval_id: str,
        body: ApprovalDecisionRequest,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> ApprovalRequestRecord:
        return await decide_approval(
            approval_id=approval_id,
            body=body,
            identity=identity,
            target=ApprovalRequestStatus.APPROVED,
        )

    @app.post(
        "/v1/approvals/{approval_id}/reject",
        response_model=ApprovalRequestRecord,
        tags=["approvals"],
    )
    async def reject(
        approval_id: str,
        body: ApprovalDecisionRequest,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> ApprovalRequestRecord:
        return await decide_approval(
            approval_id=approval_id,
            body=body,
            identity=identity,
            target=ApprovalRequestStatus.REJECTED,
        )

    @app.post(
        "/v1/approvals/{approval_id}/request-changes",
        response_model=ApprovalRequestRecord,
        tags=["approvals"],
    )
    async def request_changes(
        approval_id: str,
        body: ApprovalDecisionRequest,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> ApprovalRequestRecord:
        return await decide_approval(
            approval_id=approval_id,
            body=body,
            identity=identity,
            target=ApprovalRequestStatus.CHANGES_REQUESTED,
        )

    @app.get("/v1/audit", response_model=AuditListResponse, tags=["audit"])
    async def list_audit(
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> AuditListResponse:
        _require_roles(identity, {UserRole.AUDITOR, UserRole.PLATFORM_ADMIN})
        items = await _run_sync(governance.list_audit, identity.tenant_id, limit=limit)
        return AuditListResponse(items=items, count=len(items))

    @app.post(
        "/internal/v1/tool-intents/evaluate-and-execute",
        response_model=GatewayExecutionResult,
        tags=["internal"],
    )
    async def evaluate_and_execute(
        body: GatewayExecutionRequest,
        request: Request,
        identity: Annotated[VerifiedIdentity, Depends(_authenticate_identity)],
    ) -> GatewayExecutionResult:
        intent = body.intent
        if identity.kind is not IdentityKind.AGENT:
            raise AuthorizationError("Only authenticated agents may submit tool intents.")
        if identity.tenant_id != intent.tenant_id:
            raise AuthorizationError
        input_hash = _semantic_input_hash(intent)
        registration = registry.get(intent.tool_name)
        if registration is None:
            decision = PolicyDecision(
                decision_id=f"decision_{uuid4().hex}",
                tenant_id=intent.tenant_id,
                intent_id=intent.intent_id,
                effect=PolicyEffect.DENY,
                computed_risk=RiskLevel.UNKNOWN,
                approval_required=False,
                approval_valid=False,
                matched_policy_ids=(),
                reasons=("Tool is not registered.",),
                evaluated_at=now(),
            )
            await _run_sync(
                governance.record_audit,
                _tool_audit(
                    identity=identity,
                    intent=intent,
                    event_type="TOOL_INTENT_DENIED",
                    decision=decision,
                    input_hash=input_hash,
                    output=decision,
                    status_value=AuditStatus.REJECTED,
                    summary="Unregistered tool intent denied.",
                    now=decision.evaluated_at,
                ),
            )
            raise PolicyDeniedError
        try:
            arguments = executor.validate_arguments(intent)
        except GatewayValidationError:
            decision = PolicyDecision(
                decision_id=f"decision_{uuid4().hex}",
                tenant_id=intent.tenant_id,
                intent_id=intent.intent_id,
                effect=PolicyEffect.BLOCK_SECURITY,
                computed_risk=registration.risk_level,
                approval_required=registration.mutating,
                approval_valid=False,
                matched_policy_ids=registration.policy_ids,
                reasons=("Tool arguments failed the registered schema.",),
                evaluated_at=now(),
            )
            await _run_sync(
                governance.record_audit,
                _tool_audit(
                    identity=identity,
                    intent=intent,
                    event_type="TOOL_ARGUMENTS_BLOCKED",
                    decision=decision,
                    input_hash=input_hash,
                    output=decision,
                    status_value=AuditStatus.REJECTED,
                    summary="Out-of-schema tool arguments blocked.",
                    now=decision.evaluated_at,
                ),
            )
            raise

        change = await _run_sync(changes.get, identity.tenant_id, intent.change_id)
        plan = await _run_sync(
            governance.get_plan,
            identity.tenant_id,
            intent.change_id,
            intent.plan_id,
        )
        approval_record = (
            await _run_sync(governance.get_approval_request, identity.tenant_id, body.approval_id)
            if body.approval_id is not None
            else None
        )
        approval = approval_record.as_approval() if approval_record is not None else None
        decision = policy.evaluate(
            identity=identity,
            intent=intent,
            change=change,
            plan=plan,
            tool=registration,
            approval=approval,
            now=now(),
        )
        await _run_sync(
            governance.record_audit,
            _tool_audit(
                identity=identity,
                intent=intent,
                event_type=(
                    "TOOL_POLICY_ALLOWED"
                    if decision.effect is PolicyEffect.ALLOW
                    else "TOOL_POLICY_DENIED"
                ),
                decision=decision,
                input_hash=input_hash,
                output=decision,
                status_value=(
                    AuditStatus.SUCCESS
                    if decision.effect is PolicyEffect.ALLOW
                    else AuditStatus.REJECTED
                ),
                summary=(
                    "Deterministic tool policy allowed the exact-plan action."
                    if decision.effect is PolicyEffect.ALLOW
                    else "Deterministic tool policy denied the action."
                ),
                now=decision.evaluated_at,
            ),
        )
        if decision.effect is PolicyEffect.REQUIRE_APPROVAL:
            raise ApprovalRequiredError
        if decision.effect is not PolicyEffect.ALLOW:
            raise PolicyDeniedError

        try:
            async with quotas.acquire(intent.tenant_id, intent.tool_name):
                reservation = await _run_sync(
                    governance.reserve_execution,
                    intent=intent,
                    decision=decision,
                    approval=approval,
                    input_hash=input_hash,
                    now=now(),
                )
                if reservation.replayed:
                    if (
                        reservation.record.status is not ToolExecutionStatus.SUCCEEDED
                        or reservation.record.output is None
                        or reservation.record.output_hash is None
                    ):
                        raise RuntimeError(
                            "replayed execution is missing its validated successful result"
                        )
                    await _run_sync(
                        governance.record_audit,
                        _tool_audit(
                            identity=identity,
                            intent=intent,
                            event_type="TOOL_EXECUTION_REPLAYED",
                            decision=decision,
                            input_hash=input_hash,
                            output=reservation.record.output,
                            status_value=AuditStatus.SUCCESS,
                            summary=(
                                "Existing idempotent tool result returned without another mutation."
                            ),
                            now=now(),
                        ),
                    )
                    return GatewayExecutionResult(
                        execution_id=reservation.record.execution_id,
                        decision=decision,
                        output=reservation.record.output,
                        output_hash=reservation.record.output_hash,
                        replayed=True,
                    )
                output = await executor.execute(
                    intent=intent,
                    registration=registration,
                    arguments=arguments,
                    request_id=request.state.request_id,
                )
        except ToolAdapterError as error:
            failed_at = now()
            await _run_sync(
                governance.fail_execution,
                tenant_id=intent.tenant_id,
                change_id=intent.change_id,
                execution_id=reservation.record.execution_id,
                error_code=error.code,
                failed_at=failed_at,
            )
            await _run_sync(
                governance.record_audit,
                _tool_audit(
                    identity=identity,
                    intent=intent,
                    event_type="TOOL_EXECUTION_FAILED",
                    decision=decision,
                    input_hash=input_hash,
                    output={"error_code": error.code},
                    status_value=AuditStatus.FAILURE,
                    summary="Registered sandbox tool execution failed.",
                    now=failed_at,
                ),
            )
            raise
        output_hash = sha256_digest(output)
        completed = await _run_sync(
            governance.complete_execution,
            tenant_id=intent.tenant_id,
            change_id=intent.change_id,
            execution_id=reservation.record.execution_id,
            output=output,
            output_hash=output_hash,
            completed_at=now(),
        )
        await _run_sync(
            governance.record_audit,
            _tool_audit(
                identity=identity,
                intent=intent,
                event_type="TOOL_EXECUTION_SUCCEEDED",
                decision=decision,
                input_hash=input_hash,
                output=output,
                status_value=AuditStatus.SUCCESS,
                summary="Approved typed sandbox tool action completed.",
                now=completed.updated_at,
            ),
        )
        if completed.output is None or completed.output_hash is None:
            raise RuntimeError("completed execution is missing its validated result")
        return GatewayExecutionResult(
            execution_id=completed.execution_id,
            decision=decision,
            output=completed.output,
            output_hash=completed.output_hash,
            replayed=False,
        )

    return app
