"""Validation tests for fail-closed wire contracts."""

from datetime import UTC, datetime

import pytest
from changeops_contracts import (
    Approval,
    ChangeEnvironment,
    ChangeEvent,
    RemediationPlan,
    UserRole,
    derive_change_id,
    derive_workflow_id,
)
from pydantic import ValidationError


def test_change_event_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ChangeEvent.model_validate(
            {
                "schema_version": "1.0",
                "event_id": "evt_001",
                "tenant_id": "tenant_demo",
                "event_type": "api.contract.changed",
                "source": {
                    "type": "github",
                    "external_id": "pr-42",
                    "url": "https://example.invalid/pr/42",
                },
                "occurred_at": "2026-08-27T10:37:00Z",
                "received_at": "2026-08-27T10:37:01Z",
                "subject": {
                    "system_id": "customer-api",
                    "resource_type": "openapi-contract",
                    "resource_id": "customer-v2",
                },
                "change": {
                    "summary": "Rename customer_id to customer_uuid",
                    "old_version": "1.4.0",
                    "new_version": "2.0.0",
                    "artifact_refs": ["artifact://contracts/customer-v2-diff.json"],
                },
                "correlation_id": "corr_001",
                "trace_id": "trace_001",
                "untrusted_extra": "must fail",
            }
        )


def test_plan_rejects_non_deterministic_step_graph(remediation_plan: RemediationPlan) -> None:
    invalid = remediation_plan.model_dump(mode="python")
    invalid["steps"][0]["depends_on"] = ("missing_step",)

    with pytest.raises(ValidationError, match="unknown step dependency"):
        RemediationPlan.model_validate(invalid)


def test_approval_requires_future_expiration() -> None:
    decided_at = datetime(2026, 8, 27, 10, 38, tzinfo=UTC)
    with pytest.raises(ValidationError, match="expiration"):
        Approval(
            approval_id="approval_001",
            tenant_id="tenant_demo",
            change_id="chg_001",
            plan_id="plan_001",
            plan_hash=f"sha256:{'0' * 64}",
            plan_version=1,
            environment=ChangeEnvironment.SANDBOX,
            decision="APPROVED",
            scope=("step_crm_001",),
            approved_by="user_change_manager_001",
            approved_by_roles=(UserRole.APPROVER,),
            approved_at=decided_at,
            expires_at=decided_at,
            comment="Approved for sandbox execution.",
        )


def test_event_identifiers_are_stable_and_tenant_scoped() -> None:
    change_event = ChangeEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "evt_identifier_test",
            "tenant_id": "tenant_demo",
            "event_type": "api.contract.changed",
            "source": {
                "type": "github",
                "external_id": "pr-42",
                "url": "https://example.invalid/pr/42",
            },
            "occurred_at": "2026-08-27T10:37:00Z",
            "received_at": "2026-08-27T10:37:01Z",
            "subject": {
                "system_id": "customer-api",
                "resource_type": "openapi-contract",
                "resource_id": "customer-v2",
            },
            "change": {
                "summary": "Rename customer_id to customer_uuid",
                "old_version": "1.4.0",
                "new_version": "2.0.0",
                "artifact_refs": ["artifact://contracts/customer-v2-diff.json"],
            },
            "correlation_id": "corr_identifier_test",
            "trace_id": "trace_identifier_test",
        }
    )
    replay = ChangeEvent.model_validate(change_event.model_dump(mode="python"))
    other_tenant = ChangeEvent.model_validate(
        {**change_event.model_dump(mode="python"), "tenant_id": "tenant_other"}
    )

    assert derive_change_id(replay) == derive_change_id(change_event)
    assert derive_workflow_id(replay) == derive_workflow_id(change_event)
    assert derive_change_id(other_tenant) != derive_change_id(change_event)
    assert derive_workflow_id(other_tenant) != derive_workflow_id(change_event)
