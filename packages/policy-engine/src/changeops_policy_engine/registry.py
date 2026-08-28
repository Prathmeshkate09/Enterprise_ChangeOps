"""Closed tool registry used by policy and execution adapters."""

from __future__ import annotations

from changeops_contracts import ChangeEnvironment, RiskLevel

from changeops_policy_engine.models import ToolRegistration


class ToolRegistry:
    def __init__(self, registrations: tuple[ToolRegistration, ...]) -> None:
        by_name = {registration.tool_name: registration for registration in registrations}
        if len(by_name) != len(registrations):
            raise ValueError("tool registry names must be unique")
        self._by_name = by_name

    def get(self, tool_name: str) -> ToolRegistration | None:
        return self._by_name.get(tool_name)

    def list(self) -> tuple[ToolRegistration, ...]:
        return tuple(self._by_name[name] for name in sorted(self._by_name))


def build_default_tool_registry() -> ToolRegistry:
    def registration(
        tool_name: str,
        owning_agent_id: str,
        resource_pattern: str,
        policy_id: str,
    ) -> ToolRegistration:
        return ToolRegistration(
            tool_name=tool_name,
            owning_agent_id=owning_agent_id,
            action="update",
            resource_pattern=resource_pattern,
            risk_level=RiskLevel.HIGH,
            mutating=True,
            allowed_environments=(ChangeEnvironment.SANDBOX,),
            policy_ids=(policy_id,),
            timeout_seconds=10.0,
        )

    return ToolRegistry(
        (
            registration(
                "crm.update_field_mapping",
                "crm",
                "crm://tenant/{tenant_id}/configuration/*",
                "crm-sandbox-write-v1",
            ),
            registration(
                "analytics.update_field_mapping",
                "analytics",
                "analytics://tenant/{tenant_id}/configuration/*",
                "analytics-sandbox-write-v1",
            ),
            registration(
                "support.update_lookup_field",
                "support",
                "support://tenant/{tenant_id}/configuration/*",
                "support-sandbox-write-v1",
            ),
        )
    )
