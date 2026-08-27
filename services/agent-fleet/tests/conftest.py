"""Phase 4 test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from changeops_contracts import (
    ChangeDetails,
    ChangeEvent,
    ChangeSource,
    ChangeSubject,
    FleetAnalysisRequest,
)


@pytest.fixture
def golden_request() -> FleetAnalysisRequest:
    timestamp = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    return FleetAnalysisRequest(
        change_id="chg_phase4_golden",
        event=ChangeEvent(
            schema_version="1.0",
            event_id="evt_phase4_golden",
            tenant_id="tenant-golden",
            event_type="api.contract.changed",
            source=ChangeSource(
                type="github",
                external_id="pr-42",
                url="https://example.invalid/demo/pr/42",
            ),
            occurred_at=timestamp,
            received_at=timestamp,
            subject=ChangeSubject(
                system_id="customer-api",
                resource_type="api-contract",
                resource_id="customer-api-v2",
            ),
            change=ChangeDetails(
                summary="Rename customer_id to customer_uuid",
                old_version="1.4.0",
                new_version="2.0.0",
                artifact_refs=("artifact://contracts/customer-v2-diff.json",),
            ),
            correlation_id="correlation-phase4",
            trace_id="trace-phase4",
        ),
    )


@pytest.fixture
def evidence_payloads() -> dict[str, dict[str, Any]]:
    edges = [
        {"source": "customer-api", "target": "crm-sync", "managed": True},
        {"source": "customer-api", "target": "order-service", "managed": False},
        {"source": "customer-api", "target": "customer-daily-etl", "managed": True},
        {"source": "crm-sync", "target": "support-portal", "managed": True},
        {
            "source": "customer-daily-etl",
            "target": "customer-health-dashboard",
            "managed": True,
        },
    ]
    return {
        "catalog-contract": {
            "source_system": "catalog",
            "source_resource": "catalog://v1/contracts/customer-api",
            "attributes": {
                "identifier_field": "customer_id",
                "version": "1.4.0",
                "owner": "team://customer-platform",
            },
        },
        "catalog-dependencies": {
            "source_system": "catalog",
            "source_resource": "catalog://v1/dependencies",
            "attributes": {"items": edges},
        },
        "crm-configuration": {
            "source_system": "crm",
            "source_resource": "crm://v1/configuration",
            "attributes": {"system_id": "crm-sync", "source_field": "customer_id"},
        },
        "analytics-configuration": {
            "source_system": "analytics",
            "source_resource": "analytics://v1/configuration",
            "attributes": {
                "system_id": "customer-daily-etl",
                "source_field": "customer_id",
            },
        },
        "analytics-field-usage": {
            "source_system": "analytics",
            "source_resource": "analytics://v1/field-usage",
            "attributes": {"field": "customer_id", "resources": ["dashboard://customer-health"]},
        },
        "support-configuration": {
            "source_system": "support",
            "source_resource": "support://v1/configuration",
            "attributes": {"system_id": "support-portal", "lookup_field": "customer_id"},
        },
        "support-field-usage": {
            "source_system": "support",
            "source_resource": "support://v1/field-usage",
            "attributes": {"field": "customer_id", "resources": ["form://customer-search"]},
        },
    }
