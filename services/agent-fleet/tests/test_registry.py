from datetime import UTC, datetime

import pytest
from changeops_agent_fleet.registry import AGENT_IDS, assert_registry_is_bounded, build_registry
from changeops_contracts import AgentRegistration
from pydantic import ValidationError


def test_registry_has_exactly_seven_scoped_agents() -> None:
    registry = build_registry(
        "tenant-a", "http://agent-fleet:8200", now=datetime(2026, 8, 27, tzinfo=UTC)
    )

    assert tuple(agent.agent_id for agent in registry) == AGENT_IDS
    assert len({agent.identity_reference for agent in registry}) == 7
    assert all(agent.budget.max_model_calls == 1 for agent in registry)
    assert all(agent.budget.max_tool_calls == 0 for agent in registry)
    assert all("*" not in tool for agent in registry for tool in agent.allowed_tools)
    assert registry[0].allowed_tools == ()
    assert_registry_is_bounded(registry)


def test_contract_rejects_unrestricted_tool(registration_payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="exact registered tool names"):
        AgentRegistration.model_validate({**registration_payload, "allowed_tools": ["crm.*"]})


@pytest.fixture
def registration_payload() -> dict[str, object]:
    return build_registry("tenant-a", "http://agent-fleet:8200")[1].model_dump(mode="json")
