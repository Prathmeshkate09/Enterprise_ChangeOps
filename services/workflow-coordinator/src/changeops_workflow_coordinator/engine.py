"""Deterministic durable workflow execution, verification, and compensation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import ParamSpec, TypeVar
from uuid import uuid4

from changeops_contracts import (
    ActorType,
    AuditEvent,
    AuditStatus,
    ChangeEnvironment,
    ChangeEvent,
    ChangeRecord,
    RemediationPlan,
    RemediationStep,
    RiskLevel,
    WorkflowState,
    calculate_plan_hash,
    derive_change_id,
    derive_workflow_id,
    sha256_digest,
)
from changeops_core import StateTransitionService
from changeops_persistence import (
    ChangeAlreadyExistsError,
    ChangeNotFoundError,
    ChangeStateRepository,
)

from changeops_workflow_coordinator.clients import (
    DependencyCallError,
    FleetClient,
    GatewayClient,
    SandboxClient,
)
from changeops_workflow_coordinator.errors import (
    WorkflowNotFoundError,
    WorkflowPermanentError,
    WorkflowTransientError,
)
from changeops_workflow_coordinator.models import (
    ApprovalCallbackRequest,
    DeadLetterRecord,
    WorkflowExecutionRecord,
    WorkflowRuntimeStatus,
    WorkflowTaskRecord,
    WorkflowTaskStatus,
)
from changeops_workflow_coordinator.repository import WorkflowRepository
from changeops_workflow_coordinator.retry import RetryPolicy

P = ParamSpec("P")
R = TypeVar("R")


async def _run_sync(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    return await asyncio.to_thread(partial(function, *args, **kwargs))


class WorkflowEngine:
    def __init__(
        self,
        *,
        workflows: WorkflowRepository,
        changes: ChangeStateRepository,
        fleet: FleetClient,
        gateway: GatewayClient,
        sandboxes: SandboxClient,
        retry_policy: RetryPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflows = workflows
        self._changes = changes
        self._fleet = fleet
        self._gateway = gateway
        self._sandboxes = sandboxes
        self._retry = retry_policy
        self._clock = clock or (lambda: datetime.now(UTC))

    async def process_event(self, event: ChangeEvent) -> WorkflowExecutionRecord:
        """Create or resume one workflow for an at-least-once event delivery."""

        change_id = derive_change_id(event)
        workflow_id = derive_workflow_id(event)
        timestamp = self._clock()
        try:
            record = await _run_sync(
                self._workflows.get,
                event.tenant_id,
                change_id,
                workflow_id,
            )
            if record.status in {
                WorkflowRuntimeStatus.WAITING_APPROVAL,
                WorkflowRuntimeStatus.EXECUTING,
                WorkflowRuntimeStatus.VERIFYING,
                WorkflowRuntimeStatus.ROLLING_BACK,
                WorkflowRuntimeStatus.COMPLETED,
                WorkflowRuntimeStatus.FAILED,
                WorkflowRuntimeStatus.NEEDS_ATTENTION,
                WorkflowRuntimeStatus.DEAD_LETTERED,
            }:
                return record
            record = await self._update_record(
                record,
                delivery_attempts=record.delivery_attempts + 1,
            )
        except WorkflowNotFoundError:
            record = WorkflowExecutionRecord(
                workflow_execution_id=workflow_id,
                tenant_id=event.tenant_id,
                change_id=change_id,
                event_id=event.event_id,
                trace_id=event.trace_id,
                event=event,
                status=WorkflowRuntimeStatus.RECEIVED,
                delivery_attempts=1,
                started_at=timestamp,
                updated_at=timestamp,
                version=1,
            )
            record = await _run_sync(self._workflows.create_or_get, record)

        if event.event_type != "api.contract.changed":
            return await self._dead_letter(record, "UNSUPPORTED_EVENT_TYPE")

        await self._ensure_change(record)
        record = await self._set_runtime_status(record, WorkflowRuntimeStatus.ANALYZING)
        change = await _run_sync(self._changes.get, record.tenant_id, record.change_id)

        if change.status is WorkflowState.RECEIVED:
            change = await self._transition(
                record,
                WorkflowState.SCREENING,
                record_updates={"workflow_execution_id": record.workflow_execution_id},
            )
        if record.plan is None:
            try:
                analysis = await self._fleet.analyze(
                    change_id=record.change_id,
                    event=event,
                    request_id=f"req_{uuid4().hex}",
                )
            except DependencyCallError as error:
                if error.code == "PROMPT_INJECTION_BLOCKED":
                    await self._record_audit(
                        record,
                        event_type="SECURITY_PROMPT_INJECTION_BLOCKED",
                        action="screen_change_content",
                        input_document={"event_hash": sha256_digest(event)},
                        output_document={"decision": "blocked", "code": error.code},
                        status=AuditStatus.REJECTED,
                        summary=(
                            "Security screening blocked untrusted change content before "
                            "agent or tool execution."
                        ),
                    )
                    await self._transition(record, WorkflowState.BLOCKED)
                    return await self._terminal(
                        record,
                        WorkflowRuntimeStatus.FAILED,
                        error.code,
                    )
                if error.transient:
                    raise WorkflowTransientError(error.code) from error
                return await self._dead_letter(record, error.code)
            change = await _run_sync(self._changes.get, record.tenant_id, record.change_id)
            if change.status is WorkflowState.SCREENING:
                change = await self._transition(record, WorkflowState.ANALYZING)
            plan = analysis.draft_plan
            if (
                plan.tenant_id != record.tenant_id
                or plan.change_id != record.change_id
                or analysis.draft_plan_hash != calculate_plan_hash(plan)
            ):
                return await self._dead_letter(record, "INVALID_FLEET_PLAN")
            task_timestamp = self._clock()
            tasks = tuple(
                WorkflowTaskRecord(
                    step_id=step.step_id,
                    system_id=self._sandboxes.system_for_step(step),
                    status=WorkflowTaskStatus.PENDING,
                    attempt_count=0,
                    updated_at=task_timestamp,
                )
                for step in plan.steps
            )
            approval_id = f"approval_{record.workflow_execution_id}"
            record = await self._update_record(
                record,
                plan=plan,
                plan_hash=calculate_plan_hash(plan),
                tasks=tasks,
                approval_id=approval_id,
                approval_expires_at=self._clock() + timedelta(minutes=30),
            )

        plan = self._require_plan(record)
        change = await _run_sync(self._changes.get, record.tenant_id, record.change_id)
        if change.status is WorkflowState.SCREENING:
            change = await self._transition(record, WorkflowState.ANALYZING)
        if change.status is WorkflowState.ANALYZING:
            change = await self._transition(
                record,
                WorkflowState.PLAN_READY,
                record_updates={
                    "plan_version": plan.version,
                    "plan_hash": calculate_plan_hash(plan),
                    "risk_level": plan.risk_level,
                },
            )
        if change.status is WorkflowState.PLAN_READY:
            change = await self._transition(record, WorkflowState.AWAITING_APPROVAL)
        if change.status is not WorkflowState.AWAITING_APPROVAL:
            raise WorkflowPermanentError("CHANGE_NOT_AWAITING_APPROVAL")
        if record.approval_id is None or record.approval_expires_at is None:
            raise WorkflowPermanentError("APPROVAL_METADATA_MISSING")
        try:
            await self._gateway.create_approval(
                approval_id=record.approval_id,
                plan=plan,
                expires_at=record.approval_expires_at,
                request_id=f"req_{uuid4().hex}",
            )
        except DependencyCallError as error:
            if error.transient:
                raise WorkflowTransientError(error.code) from error
            return await self._dead_letter(record, error.code)
        return await self._set_runtime_status(record, WorkflowRuntimeStatus.WAITING_APPROVAL)

    async def resume_approval(self, callback: ApprovalCallbackRequest) -> WorkflowExecutionRecord:
        change = await _run_sync(self._changes.get, callback.tenant_id, callback.change_id)
        if change.workflow_execution_id is None:
            raise WorkflowPermanentError("WORKFLOW_ID_MISSING")
        record = await _run_sync(
            self._workflows.get,
            callback.tenant_id,
            callback.change_id,
            change.workflow_execution_id,
        )
        if record.status in {
            WorkflowRuntimeStatus.COMPLETED,
            WorkflowRuntimeStatus.FAILED,
            WorkflowRuntimeStatus.NEEDS_ATTENTION,
        }:
            return record
        plan = self._require_plan(record)
        if (
            record.approval_id != callback.approval_id
            or record.plan_hash != callback.plan_hash
            or plan.version != callback.plan_version
        ):
            raise WorkflowPermanentError("APPROVAL_CALLBACK_SCOPE_MISMATCH")
        if callback.status == "REJECTED":
            if change.status is WorkflowState.AWAITING_APPROVAL:
                await self._transition(record, WorkflowState.REJECTED)
            return await self._terminal(record, WorkflowRuntimeStatus.FAILED, "APPROVAL_REJECTED")
        if callback.status == "CHANGES_REQUESTED":
            if change.status is WorkflowState.AWAITING_APPROVAL:
                change = await self._transition(record, WorkflowState.REJECTED)
            if change.status is WorkflowState.REJECTED:
                await self._transition(record, WorkflowState.ANALYZING)
            return await self._set_runtime_status(
                record,
                WorkflowRuntimeStatus.ANALYZING,
                last_error_code="APPROVAL_CHANGES_REQUESTED",
            )

        if change.status is WorkflowState.AWAITING_APPROVAL:
            change = await self._transition(record, WorkflowState.APPROVED)
        if change.status is WorkflowState.APPROVED:
            change = await self._transition(record, WorkflowState.EXECUTING)
        if change.status is not WorkflowState.EXECUTING:
            raise WorkflowPermanentError("CHANGE_NOT_EXECUTABLE")
        record = await self._set_runtime_status(record, WorkflowRuntimeStatus.EXECUTING)
        record = await self._capture_snapshots(record)
        record = await self._execute_dag(record)
        if any(task.status is WorkflowTaskStatus.FAILED for task in record.tasks):
            return await self._rollback(record, record.last_error_code or "TOOL_EXECUTION_FAILED")

        await self._transition(record, WorkflowState.VERIFYING)
        record = await self._set_runtime_status(record, WorkflowRuntimeStatus.VERIFYING)
        verification_error = await self._verify(record)
        if verification_error is not None:
            return await self._rollback(record, verification_error)
        await self._transition(record, WorkflowState.COMPLETED)
        return await self._terminal(record, WorkflowRuntimeStatus.COMPLETED, None)

    async def _ensure_change(self, record: WorkflowExecutionRecord) -> ChangeRecord:
        try:
            return await _run_sync(self._changes.get, record.tenant_id, record.change_id)
        except ChangeNotFoundError:
            timestamp = self._clock()
            event = record.event
            change = ChangeRecord(
                change_id=record.change_id,
                tenant_id=record.tenant_id,
                event_id=record.event_id,
                change_type=event.event_type,
                title=event.change.summary,
                description=event.change.summary,
                source=event.source,
                environment=ChangeEnvironment.SANDBOX,
                status=WorkflowState.RECEIVED,
                risk_level=RiskLevel.UNKNOWN,
                current_phase=WorkflowState.RECEIVED,
                workflow_execution_id=None,
                plan_version=0,
                plan_hash=None,
                created_at=timestamp,
                updated_at=timestamp,
                created_by="event-gateway",
                version=1,
            )
            audit = self._audit(
                record,
                event_type="CHANGE_RECEIVED",
                action="create_change",
                input_document={"event_id": event.event_id},
                output_document=change,
                status=AuditStatus.SUCCESS,
                summary="Authenticated change event accepted for durable processing.",
            )
            try:
                await _run_sync(self._changes.add_with_audit, change, audit)
            except ChangeAlreadyExistsError:
                existing = await _run_sync(self._changes.get, record.tenant_id, record.change_id)
                if existing.event_id != record.event_id:
                    raise WorkflowPermanentError("CHANGE_ID_COLLISION") from None
                return existing
            return change

    async def _capture_snapshots(self, record: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        missing = [task for task in record.tasks if task.snapshot_id is None]
        if not missing:
            return record
        snapshots = await asyncio.gather(
            *(
                self._sandboxes.snapshot(
                    system=task.system_id,
                    tenant_id=record.tenant_id,
                    request_id=f"req_{uuid4().hex}",
                )
                for task in missing
            ),
            return_exceptions=True,
        )
        by_step = {task.step_id: task for task in record.tasks}
        for task, result in zip(missing, snapshots, strict=True):
            if isinstance(result, BaseException):
                if isinstance(result, DependencyCallError) and result.transient:
                    raise WorkflowTransientError(result.code) from result
                raise WorkflowPermanentError("SNAPSHOT_CAPTURE_FAILED") from result
            by_step[task.step_id] = WorkflowTaskRecord.model_validate(
                {
                    **task.model_dump(mode="python"),
                    "snapshot_id": result.snapshot_id,
                    "snapshot_hash": result.configuration_hash,
                    "updated_at": self._clock(),
                }
            )
            await self._record_audit(
                record,
                event_type="WORKFLOW_SNAPSHOT_CAPTURED",
                action="capture_snapshot",
                input_document={"step_id": task.step_id, "system_id": task.system_id},
                output_document={
                    "snapshot_id": result.snapshot_id,
                    "snapshot_hash": result.configuration_hash,
                },
                status=AuditStatus.SUCCESS,
                summary=f"Pre-write {task.system_id} snapshot captured and hashed.",
            )
        return await self._update_record(
            record,
            tasks=tuple(by_step[task.step_id] for task in record.tasks),
        )

    async def _execute_dag(self, record: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        plan = self._require_plan(record)
        by_step = {task.step_id: task for task in record.tasks}
        steps = {step.step_id: step for step in plan.steps}
        while True:
            pending = [
                task for task in by_step.values() if task.status is WorkflowTaskStatus.PENDING
            ]
            if not pending:
                break
            succeeded = {
                task.step_id
                for task in by_step.values()
                if task.status is WorkflowTaskStatus.SUCCEEDED
            }
            ready = [
                task for task in pending if set(steps[task.step_id].depends_on).issubset(succeeded)
            ]
            if not ready:
                raise WorkflowPermanentError("DAG_PROGRESS_BLOCKED")
            results = await asyncio.gather(
                *(self._execute_task(record, task, steps[task.step_id]) for task in ready)
            )
            for result in results:
                by_step[result.step_id] = result
            record = await self._update_record(
                record,
                tasks=tuple(by_step[task.step_id] for task in record.tasks),
                last_error_code=next(
                    (
                        task.error_code
                        for task in results
                        if task.status is WorkflowTaskStatus.FAILED
                    ),
                    None,
                ),
            )
            if any(task.status is WorkflowTaskStatus.FAILED for task in results):
                break
        return record

    async def _execute_task(
        self,
        record: WorkflowExecutionRecord,
        task: WorkflowTaskRecord,
        step: RemediationStep,
    ) -> WorkflowTaskRecord:
        plan = self._require_plan(record)
        if record.approval_id is None:
            raise WorkflowPermanentError("APPROVAL_ID_MISSING")
        attempt = task.attempt_count
        while True:
            attempt += 1
            try:
                result = await self._gateway.execute(
                    workflow_execution_id=record.workflow_execution_id,
                    plan=plan,
                    step=step,
                    approval_id=record.approval_id,
                    requested_at=self._clock(),
                    request_id=f"req_{uuid4().hex}",
                )
                await self._record_audit(
                    record,
                    event_type="WORKFLOW_STEP_SUCCEEDED",
                    action="execute_plan_step",
                    input_document={"attempt": attempt, "step_id": step.step_id},
                    output_document={
                        "execution_id": result.execution_id,
                        "output_hash": result.output_hash,
                        "replayed": result.replayed,
                    },
                    status=AuditStatus.SUCCESS,
                    summary=f"Approved {task.system_id} workflow step completed.",
                )
                return WorkflowTaskRecord.model_validate(
                    {
                        **task.model_dump(mode="python"),
                        "status": WorkflowTaskStatus.SUCCEEDED,
                        "attempt_count": attempt,
                        "execution_id": result.execution_id,
                        "output_hash": result.output_hash,
                        "error_code": None,
                        "updated_at": self._clock(),
                    }
                )
            except DependencyCallError as error:
                if self._retry.should_retry(transient=error.transient, attempt=attempt):
                    await self._record_audit(
                        record,
                        event_type="WORKFLOW_STEP_RETRY_SCHEDULED",
                        action="retry_plan_step",
                        input_document={
                            "attempt": attempt,
                            "error_code": error.code,
                            "step_id": step.step_id,
                        },
                        output_document={"next_attempt": attempt + 1},
                        status=AuditStatus.FAILURE,
                        summary=f"Transient {task.system_id} failure scheduled for bounded retry.",
                    )
                    await asyncio.sleep(self._retry.delay(attempt))
                    continue
                await self._record_audit(
                    record,
                    event_type="WORKFLOW_STEP_FAILED",
                    action="execute_plan_step",
                    input_document={"attempt": attempt, "step_id": step.step_id},
                    output_document={"error_code": error.code},
                    status=AuditStatus.FAILURE,
                    summary=f"{task.system_id} workflow step exhausted its allowed attempts.",
                )
                return WorkflowTaskRecord.model_validate(
                    {
                        **task.model_dump(mode="python"),
                        "status": WorkflowTaskStatus.FAILED,
                        "attempt_count": attempt,
                        "error_code": error.code,
                        "updated_at": self._clock(),
                    }
                )

    async def _verify(self, record: WorkflowExecutionRecord) -> str | None:
        plan = self._require_plan(record)
        step_by_id = {step.step_id: step for step in plan.steps}
        results = await asyncio.gather(
            *(self._verify_task(record, task, step_by_id[task.step_id]) for task in record.tasks),
            return_exceptions=True,
        )
        for task, result in zip(record.tasks, results, strict=True):
            if isinstance(result, BaseException):
                code = result.code if isinstance(result, DependencyCallError) else "VERIFY_FAILED"
                return code
            if not result:
                return f"{task.system_id.upper()}_VERIFICATION_FAILED"
        return None

    async def _verify_task(
        self,
        record: WorkflowExecutionRecord,
        task: WorkflowTaskRecord,
        step: RemediationStep,
    ) -> bool:
        expected = step.arguments.get("new_field")
        if not isinstance(expected, str):
            raise DependencyCallError("VERIFICATION_ARGUMENT_MISSING", transient=False)
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await self._sandboxes.verify(
                    system=task.system_id,
                    tenant_id=record.tenant_id,
                    expected_field=expected,
                    request_id=f"req_{uuid4().hex}",
                )
                await self._record_audit(
                    record,
                    event_type=(
                        "WORKFLOW_VERIFICATION_SUCCEEDED"
                        if result.passed
                        else "WORKFLOW_VERIFICATION_FAILED"
                    ),
                    action="verify_system",
                    input_document={"expected_field": expected, "system_id": task.system_id},
                    output_document=result,
                    status=AuditStatus.SUCCESS if result.passed else AuditStatus.FAILURE,
                    summary=f"Independent {task.system_id} verification completed.",
                )
                return result.passed
            except DependencyCallError as error:
                if self._retry.should_retry(transient=error.transient, attempt=attempt):
                    await asyncio.sleep(self._retry.delay(attempt))
                    continue
                raise

    async def _rollback(
        self, record: WorkflowExecutionRecord, original_error: str
    ) -> WorkflowExecutionRecord:
        change = await _run_sync(self._changes.get, record.tenant_id, record.change_id)
        if change.status in {WorkflowState.EXECUTING, WorkflowState.VERIFYING}:
            await self._transition(record, WorkflowState.ROLLING_BACK)
        record = await self._set_runtime_status(
            record,
            WorkflowRuntimeStatus.ROLLING_BACK,
            last_error_code=original_error,
        )
        plan = self._require_plan(record)
        order = {step.step_id: step.order for step in plan.steps}
        by_step = {task.step_id: task for task in record.tasks}
        rollback_failed = False
        for task in sorted(record.tasks, key=lambda item: order[item.step_id], reverse=True):
            if task.snapshot_id is None or task.snapshot_hash is None:
                rollback_failed = True
                by_step[task.step_id] = WorkflowTaskRecord.model_validate(
                    {
                        **task.model_dump(mode="python"),
                        "status": WorkflowTaskStatus.ROLLBACK_FAILED,
                        "error_code": "SNAPSHOT_MISSING",
                        "updated_at": self._clock(),
                    }
                )
                continue
            try:
                await self._sandboxes.restore(
                    system=task.system_id,
                    tenant_id=record.tenant_id,
                    snapshot_id=task.snapshot_id,
                    request_id=f"req_{uuid4().hex}",
                )
                restored_hash = await self._sandboxes.configuration_hash(
                    system=task.system_id,
                    tenant_id=record.tenant_id,
                    request_id=f"req_{uuid4().hex}",
                )
                if restored_hash != task.snapshot_hash:
                    raise DependencyCallError("RESTORE_HASH_MISMATCH", transient=False)
                by_step[task.step_id] = WorkflowTaskRecord.model_validate(
                    {
                        **task.model_dump(mode="python"),
                        "status": WorkflowTaskStatus.ROLLED_BACK,
                        "error_code": None,
                        "updated_at": self._clock(),
                    }
                )
                await self._record_audit(
                    record,
                    event_type="WORKFLOW_ROLLBACK_SUCCEEDED",
                    action="restore_snapshot",
                    input_document={
                        "snapshot_id": task.snapshot_id,
                        "system_id": task.system_id,
                    },
                    output_document={"configuration_hash": restored_hash},
                    status=AuditStatus.SUCCESS,
                    summary=f"{task.system_id} snapshot restored and hash verified.",
                )
            except DependencyCallError as error:
                rollback_failed = True
                by_step[task.step_id] = WorkflowTaskRecord.model_validate(
                    {
                        **task.model_dump(mode="python"),
                        "status": WorkflowTaskStatus.ROLLBACK_FAILED,
                        "error_code": error.code,
                        "updated_at": self._clock(),
                    }
                )
                await self._record_audit(
                    record,
                    event_type="WORKFLOW_ROLLBACK_FAILED",
                    action="restore_snapshot",
                    input_document={"system_id": task.system_id},
                    output_document={"error_code": error.code},
                    status=AuditStatus.FAILURE,
                    summary=f"{task.system_id} rollback requires operator attention.",
                )
        record = await self._update_record(
            record,
            tasks=tuple(by_step[task.step_id] for task in record.tasks),
        )
        target = WorkflowState.NEEDS_ATTENTION if rollback_failed else WorkflowState.FAILED
        await self._transition(record, target)
        return await self._terminal(
            record,
            (
                WorkflowRuntimeStatus.NEEDS_ATTENTION
                if rollback_failed
                else WorkflowRuntimeStatus.FAILED
            ),
            original_error,
        )

    async def _dead_letter(
        self, record: WorkflowExecutionRecord, error_code: str
    ) -> WorkflowExecutionRecord:
        terminal = await self._terminal(
            record,
            WorkflowRuntimeStatus.DEAD_LETTERED,
            error_code,
        )
        dead_letter = DeadLetterRecord(
            dead_letter_id=f"dlq_{record.workflow_execution_id}",
            tenant_id=record.tenant_id,
            event_id=record.event_id,
            workflow_execution_id=record.workflow_execution_id,
            error_code=error_code,
            input_hash=sha256_digest(record.event),
            created_at=self._clock(),
        )
        await _run_sync(self._workflows.record_dead_letter, dead_letter)
        return terminal

    async def _transition(
        self,
        record: WorkflowExecutionRecord,
        target: WorkflowState,
        *,
        record_updates: dict[str, object] | None = None,
    ) -> ChangeRecord:
        current = await _run_sync(self._changes.get, record.tenant_id, record.change_id)
        service = StateTransitionService(self._changes, clock=self._clock)
        return await _run_sync(
            service.transition,
            tenant_id=record.tenant_id,
            change_id=record.change_id,
            target=target,
            expected_version=current.version,
            trace_id=record.trace_id,
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
            record_updates=record_updates,
        )

    async def _set_runtime_status(
        self,
        record: WorkflowExecutionRecord,
        status: WorkflowRuntimeStatus,
        *,
        last_error_code: str | None = None,
    ) -> WorkflowExecutionRecord:
        if record.status is status and record.last_error_code == last_error_code:
            return record
        return await self._update_record(
            record,
            status=status,
            last_error_code=last_error_code,
        )

    async def _terminal(
        self,
        record: WorkflowExecutionRecord,
        status: WorkflowRuntimeStatus,
        error_code: str | None,
    ) -> WorkflowExecutionRecord:
        if record.status is status and record.completed_at is not None:
            return record
        return await self._update_record(
            record,
            status=status,
            last_error_code=error_code,
            completed_at=self._clock(),
        )

    async def _update_record(
        self, record: WorkflowExecutionRecord, **updates: object
    ) -> WorkflowExecutionRecord:
        updated = WorkflowExecutionRecord.model_validate(
            {
                **record.model_dump(mode="python"),
                **updates,
                "updated_at": self._clock(),
                "version": record.version + 1,
            }
        )
        return await _run_sync(self._workflows.update, updated, expected_version=record.version)

    @staticmethod
    def _require_plan(record: WorkflowExecutionRecord) -> RemediationPlan:
        if record.plan is None:
            raise WorkflowPermanentError("PLAN_MISSING")
        return record.plan

    def _audit(
        self,
        record: WorkflowExecutionRecord,
        *,
        event_type: str,
        action: str,
        input_document: object,
        output_document: object,
        status: AuditStatus,
        summary: str,
    ) -> AuditEvent:
        input_hash = sha256_digest({"value": str(input_document)})
        output_hash = sha256_digest({"value": str(output_document)})
        if hasattr(input_document, "model_dump"):
            input_hash = sha256_digest(input_document)  # type: ignore[arg-type]
        elif isinstance(input_document, dict):
            input_hash = sha256_digest(input_document)
        if hasattr(output_document, "model_dump"):
            output_hash = sha256_digest(output_document)  # type: ignore[arg-type]
        elif isinstance(output_document, dict):
            output_hash = sha256_digest(output_document)
        return AuditEvent(
            audit_event_id=f"audit_{uuid4().hex}",
            tenant_id=record.tenant_id,
            change_id=record.change_id,
            trace_id=record.trace_id,
            event_type=event_type,
            actor_type=ActorType.SERVICE,
            actor_id="workflow-coordinator",
            resource=f"workflows/{record.workflow_execution_id}",
            action=action,
            input_hash=input_hash,
            output_hash=output_hash,
            status=status,
            redacted_summary=summary,
            created_at=self._clock(),
        )

    async def _record_audit(self, record: WorkflowExecutionRecord, **values: object) -> None:
        audit = self._audit(record, **values)  # type: ignore[arg-type]
        await _run_sync(self._changes.record_audit, audit)
