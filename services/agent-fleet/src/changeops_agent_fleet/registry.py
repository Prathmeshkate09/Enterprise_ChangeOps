"""Tenant-scoped registry for the seven Phase 4 agents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from changeops_contracts import (
    AgentInvocationBudget,
    AgentRegistration,
    AgentStatus,
    RiskLevel,
)
from pydantic import AnyUrl

AGENT_IDS = (
    "orchestrator",
    "impact-analysis",
    "compliance",
    "crm",
    "analytics",
    "support",
    "verification",
)


class _AgentDefinition(TypedDict):
    display_name: str
    description: str
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    resources: tuple[str, ...]
    risk: RiskLevel


_DEFINITIONS: dict[str, _AgentDefinition] = {
    "orchestrator": {
        "display_name": "Orchestrator",
        "description": "Normalizes objectives and coordinates bounded specialist analysis.",
        "capabilities": ("normalize-change", "select-specialists", "consolidate-findings"),
        "tools": (),
        "resources": ("change://tenant/{tenant_id}/*",),
        "risk": RiskLevel.HIGH,
    },
    "impact-analysis": {
        "display_name": "Impact Analysis",
        "description": "Finds affected systems, dependency paths, owners, and unknowns.",
        "capabilities": ("dependency-analysis", "schema-usage-analysis"),
        "tools": (
            "catalog.get_change_diff",
            "catalog.query_dependency_graph",
            "catalog.search_schema_usage",
            "catalog.get_system_metadata",
            "catalog.get_system_owners",
            "memory.search_similar_changes",
        ),
        "resources": ("catalog://tenant/{tenant_id}/*", "memory://tenant/{tenant_id}/*"),
        "risk": RiskLevel.CRITICAL,
    },
    "compliance": {
        "display_name": "Compliance",
        "description": "Recommends applicable policy while leaving enforcement deterministic.",
        "capabilities": ("policy-discovery", "approval-recommendation"),
        "tools": (
            "policy.search",
            "policy.get_by_id",
            "catalog.get_data_classification",
            "catalog.get_environment",
            "catalog.get_change_window",
        ),
        "resources": ("policy://tenant/{tenant_id}/*", "catalog://tenant/{tenant_id}/*"),
        "risk": RiskLevel.CRITICAL,
    },
    "crm": {
        "display_name": "CRM",
        "description": "Inspects CRM mappings and proposes a bounded mapping patch.",
        "capabilities": ("crm-schema-inspection", "crm-patch-proposal"),
        "tools": ("crm.inspect_schema", "crm.inspect_mapping", "crm.update_field_mapping"),
        "resources": ("crm://tenant/{tenant_id}/configuration/*",),
        "risk": RiskLevel.HIGH,
    },
    "analytics": {
        "display_name": "Analytics",
        "description": "Inspects data dependencies and proposes a bounded mapping patch.",
        "capabilities": ("analytics-impact-analysis", "analytics-patch-proposal"),
        "tools": (
            "analytics.search_field_usage",
            "analytics.inspect_pipeline",
            "analytics.inspect_dashboard_dependencies",
            "analytics.update_field_mapping",
        ),
        "resources": ("analytics://tenant/{tenant_id}/configuration/*",),
        "risk": RiskLevel.HIGH,
    },
    "support": {
        "display_name": "Support",
        "description": "Inspects lookup dependencies and proposes a bounded lookup patch.",
        "capabilities": ("support-impact-analysis", "support-patch-proposal"),
        "tools": (
            "support.inspect_lookup_configuration",
            "support.inspect_form_dependencies",
            "support.update_lookup_field",
        ),
        "resources": ("support://tenant/{tenant_id}/configuration/*",),
        "risk": RiskLevel.HIGH,
    },
    "verification": {
        "display_name": "Verification",
        "description": "Defines read-only validation and explicit partial/failure handling.",
        "capabilities": ("contract-verification", "cross-system-verification"),
        "tools": (
            "verify.run_contract_suite",
            "verify.run_cross_system_suite",
            "verify.query_health",
            "verify.compare_before_after",
            "verify.check_audit_completeness",
        ),
        "resources": ("verification://tenant/{tenant_id}/*",),
        "risk": RiskLevel.CRITICAL,
    },
}


def build_registry(
    tenant_id: str,
    runtime_base_url: str,
    *,
    now: datetime | None = None,
) -> tuple[AgentRegistration, ...]:
    """Build immutable tenant-scoped registrations from fixed templates."""

    timestamp = now or datetime.now(UTC)
    base = runtime_base_url.rstrip("/")
    registrations: list[AgentRegistration] = []
    for agent_id in AGENT_IDS:
        definition = _DEFINITIONS[agent_id]
        registrations.append(
            AgentRegistration(
                agent_id=agent_id,
                tenant_id=tenant_id,
                display_name=str(definition["display_name"]),
                description=str(definition["description"]),
                version="1.0.0",
                owner="team://changeops-platform",
                capabilities=definition["capabilities"],
                allowed_tools=definition["tools"],
                allowed_resource_patterns=tuple(
                    str(pattern).format(tenant_id=tenant_id) for pattern in definition["resources"]
                ),
                risk_ceiling=definition["risk"],
                runtime_endpoint=AnyUrl(f"{base}/v1/agents/{agent_id}"),
                identity_reference=f"identity://local/{tenant_id}/{agent_id}-v1",
                status=AgentStatus.ACTIVE,
                budget=AgentInvocationBudget(
                    max_model_calls=1,
                    max_tool_calls=0,
                    max_turns=1,
                    timeout_seconds=30,
                ),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return tuple(registrations)


def assert_registry_is_bounded(registry: tuple[AgentRegistration, ...]) -> None:
    """Fail closed when registry shape or tool scope violates the Phase 4 boundary."""

    if tuple(item.agent_id for item in registry) != AGENT_IDS:
        raise ValueError("the fleet must contain exactly the seven registered agents")
    if registry[0].allowed_tools:
        raise ValueError("the orchestrator cannot have enterprise-system tools")
    prohibited = ("apply_", "restore_", "snapshot_", "shell", "execute_sql", "http_request")
    for registration in registry:
        if any(marker in tool for tool in registration.allowed_tools for marker in prohibited):
            raise ValueError(f"agent {registration.agent_id} has an executable write tool")
