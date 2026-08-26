"""Validation tests for fail-closed wire contracts."""

from datetime import UTC, datetime

import pytest
from changeops_contracts import Approval, ChangeEvent, RemediationPlan
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
            decision="APPROVED",
            scope=("step_crm_001",),
            approved_by="user_change_manager_001",
            approved_at=decided_at,
            expires_at=decided_at,
            comment="Approved for sandbox execution.",
        )
