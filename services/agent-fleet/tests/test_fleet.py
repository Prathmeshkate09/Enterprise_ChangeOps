from typing import Any

import pytest
from changeops_agent_fleet.evidence import StaticEvidenceProvider
from changeops_agent_fleet.fleet import AgentFleet
from changeops_contracts import FleetAnalysisRequest, calculate_plan_hash
from changeops_core import AgentModelMode, Settings


@pytest.mark.asyncio
async def test_golden_event_produces_evidence_backed_parallel_proposals(
    golden_request: FleetAnalysisRequest,
    evidence_payloads: dict[str, dict[str, Any]],
) -> None:
    fleet = AgentFleet(
        settings=Settings(agent_model_mode=AgentModelMode.FAKE),
        evidence_provider=StaticEvidenceProvider(evidence_payloads),
    )

    result = await fleet.analyze(golden_request)

    assert "support-portal" in result.impact.affected_systems
    assert len(result.remediation_proposals) == 3
    assert {proposal.agent_id for proposal in result.remediation_proposals} == {
        "crm",
        "analytics",
        "support",
    }
    assert all(proposal.evidence_refs for proposal in result.remediation_proposals)
    assert all(proposal.requires_approval for proposal in result.remediation_proposals)
    assert len(result.invocations) == 7
    assert all(invocation.model_calls == 1 for invocation in result.invocations)
    assert all(invocation.tool_calls == 0 for invocation in result.invocations)
    assert result.max_parallel_agents >= 3
    assert result.draft_plan_hash == calculate_plan_hash(result.draft_plan)
    memory = next(item for item in result.evidence if item.evidence_id.startswith("memory-"))
    assert memory.evidence_id in result.impact.evidence_refs
    assert memory.evidence_id in result.orchestration.evidence_refs


@pytest.mark.asyncio
async def test_fake_model_is_deterministic_for_domain_outputs(
    golden_request: FleetAnalysisRequest,
    evidence_payloads: dict[str, dict[str, Any]],
) -> None:
    fleet = AgentFleet(
        settings=Settings(agent_model_mode="fake"),
        evidence_provider=StaticEvidenceProvider(evidence_payloads),
    )

    first = await fleet.analyze(golden_request)
    second = await fleet.analyze(golden_request)

    assert first.impact == second.impact
    assert first.compliance == second.compliance
    assert first.remediation_proposals == second.remediation_proposals
    assert first.draft_plan_hash == second.draft_plan_hash
