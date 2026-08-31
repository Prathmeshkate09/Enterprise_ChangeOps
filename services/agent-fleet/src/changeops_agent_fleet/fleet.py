"""Seven-agent Google ADK workflow and deterministic plan consolidation."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from changeops_contracts import (
    AgentInvocationRecord,
    AgentRegistration,
    ComplianceAnalysis,
    DependencyPath,
    EvidenceItem,
    FleetAnalysisRequest,
    FleetAnalysisResult,
    ImpactAnalysis,
    OrchestrationDirective,
    RemediationPlan,
    RemediationProposal,
    RemediationStep,
    RiskLevel,
    VerificationProposal,
    calculate_plan_hash,
    sha256_digest,
)
from changeops_core import AgentModelMode, Settings
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import START, JoinNode, Workflow
from google.genai import types
from pydantic import BaseModel, JsonValue

from changeops_agent_fleet.evidence import EvidenceProvider, field_transition
from changeops_agent_fleet.governance import GovernanceService, build_governance
from changeops_agent_fleet.models import (
    DeterministicModel,
    InvocationTracker,
    model_name,
    output_from_state,
)
from changeops_agent_fleet.registry import AGENT_IDS, assert_registry_is_bounded, build_registry

_OUTPUT_TYPES: dict[str, type[BaseModel]] = {
    "orchestrator": OrchestrationDirective,
    "impact-analysis": ImpactAnalysis,
    "compliance": ComplianceAnalysis,
    "crm": RemediationProposal,
    "analytics": RemediationProposal,
    "support": RemediationProposal,
    "verification": VerificationProposal,
}


class AgentFleet:
    """Runs evidence-backed analysis; it never executes proposed writes."""

    def __init__(
        self,
        *,
        settings: Settings,
        evidence_provider: EvidenceProvider,
        governance: GovernanceService | None = None,
        runtime_base_url: str = "http://127.0.0.1:8200",
    ) -> None:
        self._settings = settings
        self._evidence_provider = evidence_provider
        self._governance = governance or build_governance(settings)
        self._runtime_base_url = runtime_base_url

    def registrations(self, tenant_id: str) -> tuple[AgentRegistration, ...]:
        registry = build_registry(
            tenant_id,
            self._runtime_base_url,
            identity_reference=self._governance.identity_reference,
        )
        assert_registry_is_bounded(registry)
        return registry

    async def analyze(self, request: FleetAnalysisRequest) -> FleetAnalysisResult:
        started_at = datetime.now(UTC)
        memory_evidence = await self._governance.prepare(request.event)
        evidence = (*await self._evidence_provider.collect(request.event), *memory_evidence)
        registry = self.registrations(request.event.tenant_id)
        tracker = InvocationTracker()
        expected = _derive_outputs(request, evidence)
        models = self._build_models(expected, tracker)
        workflow = self._build_workflow(models, tracker)
        session_service = InMemorySessionService()
        session_id = f"analysis-{uuid5(NAMESPACE_URL, request.change_id).hex}"
        runner = Runner(
            app_name="enterprise-changeops-agent-fleet",
            node=workflow,
            session_service=session_service,
            auto_create_session=True,
        )
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=json.dumps(
                        {
                            "request": request.model_dump(mode="json"),
                            "evidence": [item.model_dump(mode="json") for item in evidence],
                        },
                        sort_keys=True,
                    )
                )
            ],
        )
        async for _ in runner.run_async(
            user_id=request.event.tenant_id,
            session_id=session_id,
            new_message=message,
        ):
            pass
        session = await session_service.get_session(
            app_name="enterprise-changeops-agent-fleet",
            user_id=request.event.tenant_id,
            session_id=session_id,
        )
        if session is None:
            raise RuntimeError("ADK session disappeared before outputs were read")
        outputs = {
            agent_id: output_from_state(session.state[f"output_{agent_id}"], output_type)
            for agent_id, output_type in _OUTPUT_TYPES.items()
        }
        orchestration = OrchestrationDirective.model_validate(outputs["orchestrator"])
        impact = ImpactAnalysis.model_validate(outputs["impact-analysis"])
        compliance = ComplianceAnalysis.model_validate(outputs["compliance"])
        verification = VerificationProposal.model_validate(outputs["verification"])
        proposals = (
            RemediationProposal.model_validate(outputs["crm"]),
            RemediationProposal.model_validate(outputs["analytics"]),
            RemediationProposal.model_validate(outputs["support"]),
        )
        plan = _build_plan(
            request,
            proposals,
            evidence,
        )
        invocations = tuple(
            _invocation_record(
                registration,
                outputs[registration.agent_id],
                models[registration.agent_id],
                tracker,
            )
            for registration in registry
        )
        completed_at = datetime.now(UTC)
        return FleetAnalysisResult(
            analysis_id=f"analysis_{uuid5(NAMESPACE_URL, request.change_id).hex}",
            tenant_id=request.event.tenant_id,
            change_id=request.change_id,
            trace_id=request.event.trace_id,
            model_mode=self._settings.agent_model_mode.value,
            orchestration=orchestration,
            impact=impact,
            compliance=compliance,
            remediation_proposals=proposals,
            verification=verification,
            draft_plan=plan,
            draft_plan_hash=calculate_plan_hash(plan),
            evidence=evidence,
            invocations=invocations,
            max_parallel_agents=tracker.max_parallel,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _build_models(
        self,
        outputs: dict[str, BaseModel],
        tracker: InvocationTracker,
    ) -> dict[str, str | BaseLlm]:
        if self._settings.agent_model_mode is AgentModelMode.LIVE:
            return {
                agent_id: (
                    self._settings.gemini_light_model
                    if agent_id in {"orchestrator", "compliance", "verification"}
                    else self._settings.gemini_primary_model
                )
                for agent_id in AGENT_IDS
            }
        return {
            agent_id: DeterministicModel(
                agent_id=agent_id,
                responder=_response_for(outputs[agent_id]),
                tracker=tracker,
            )
            for agent_id in AGENT_IDS
        }

    def _build_workflow(
        self,
        models: dict[str, str | BaseLlm],
        tracker: InvocationTracker,
    ) -> Workflow:
        agents: dict[str, LlmAgent] = {}
        for agent_id in AGENT_IDS:
            registration = next(
                item for item in self.registrations("runtime") if item.agent_id == agent_id
            )

            async def before(callback_context: Any, current: str = agent_id) -> None:
                del callback_context
                await tracker.enter(current)

            async def after(callback_context: Any, current: str = agent_id) -> None:
                del callback_context
                await tracker.exit(current)

            agents[agent_id] = LlmAgent(
                name=agent_id.replace("-", "_"),
                description=registration.description,
                model=models[agent_id],
                instruction=_instruction(agent_id, registration),
                tools=[],
                output_schema=_OUTPUT_TYPES[agent_id],
                output_key=f"output_{agent_id}",
                mode="single_turn",
                timeout=self._settings.agent_model_timeout_seconds,
                before_agent_callback=before,
                after_agent_callback=after,
                disallow_transfer_to_parent=True,
                disallow_transfer_to_peers=True,
            )
        analysis_join = JoinNode(name="consolidate_analysis")
        proposal_join = JoinNode(name="consolidate_proposals")
        return Workflow(
            name="phase4_agent_fleet",
            max_concurrency=3,
            edges=[
                (
                    START,
                    agents["orchestrator"],
                    (agents["impact-analysis"], agents["compliance"]),
                    analysis_join,
                    (agents["crm"], agents["analytics"], agents["support"]),
                    proposal_join,
                    agents["verification"],
                )
            ],
        )


def _instruction(agent_id: str, registration: AgentRegistration) -> str:
    return (
        f"You are the {registration.display_name} agent. Return only the requested JSON schema. "
        "Use only evidence IDs supplied in the user message, preserve disagreements and unknowns, "
        "and never invent enterprise state. This Phase 4 run is analysis-only: "
        "do not execute tools. "
        f"Your registered tool names are {list(registration.allowed_tools)}."
    )


def _derive_outputs(
    request: FleetAnalysisRequest,
    evidence: tuple[EvidenceItem, ...],
) -> dict[str, BaseModel]:
    event = request.event
    by_id = {item.evidence_id: item for item in evidence}
    old_field, new_field = field_transition(event)
    raw_edges = by_id["catalog-dependencies"].attributes.get("items", [])
    edges = raw_edges if isinstance(raw_edges, list) else []
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if isinstance(edge, dict) and edge.get("managed") is True:
            graph[str(edge["source"])].append(str(edge["target"]))
    unmanaged = tuple(
        str(edge["target"])
        for edge in edges
        if isinstance(edge, dict) and edge.get("managed") is False
    )
    paths = _dependency_paths(event.subject.system_id, graph)
    affected = tuple(dict.fromkeys(node for path in paths for node in path)) or (
        event.subject.system_id,
    )
    evidence_refs = tuple(item.evidence_id for item in evidence)
    memory_refs = tuple(
        item.evidence_id for item in evidence if item.evidence_id.startswith("memory-")
    )
    impact_refs = ("catalog-contract", "catalog-dependencies", *memory_refs)
    specialists = tuple(agent_id for agent_id in AGENT_IDS if agent_id != "orchestrator")
    outputs: dict[str, BaseModel] = {
        "orchestrator": OrchestrationDirective(
            tenant_id=event.tenant_id,
            change_id=request.change_id,
            normalized_objective=(
                f"Assess and propose sandbox-safe migration from {old_field} to {new_field} "
                "across managed dependencies."
            ),
            selected_agent_ids=specialists,
            evidence_refs=impact_refs,
            confidence=0.96,
            unknowns=tuple(
                f"Unmanaged dependency {target} requires owner-led follow-up."
                for target in unmanaged
            ),
        ),
        "impact-analysis": ImpactAnalysis(
            tenant_id=event.tenant_id,
            change_id=request.change_id,
            affected_systems=affected,
            dependency_paths=tuple(
                DependencyPath(systems=path, evidence_refs=("catalog-dependencies",))
                for path in paths
            ),
            severity=RiskLevel.HIGH,
            confidence=0.95,
            evidence_refs=impact_refs,
            owner_refs=(str(by_id["catalog-contract"].attributes.get("owner", "owner://unknown")),),
            unknowns=(
                *tuple(
                    f"The unmanaged {target} impact is not automatically remediable."
                    for target in unmanaged
                ),
                *tuple(
                    "Historical incident memory must be corroborated against current "
                    "platform evidence."
                    for _ in memory_refs[:1]
                ),
            ),
        ),
        "compliance": _compliance_output(request, by_id["policy-sandbox-change"]),
    }
    proposal_specs = (
        ("crm", "crm.update_field_mapping", "crm-configuration"),
        (
            "analytics",
            "analytics.update_field_mapping",
            "analytics-configuration",
        ),
        ("support", "support.update_lookup_field", "support-configuration"),
    )
    for agent_id, tool, configuration_ref in proposal_specs:
        target = _required_string(by_id[configuration_ref].attributes["system_id"])
        outputs[agent_id] = RemediationProposal(
            proposal_id=f"proposal_{agent_id}_{uuid5(NAMESPACE_URL, request.change_id).hex[:12]}",
            tenant_id=event.tenant_id,
            change_id=request.change_id,
            agent_id=agent_id,
            target_system=target,
            summary=f"Propose changing {target} from {old_field} to {new_field}.",
            proposed_tool=tool,
            target_resource=f"{agent_id}://tenant/{event.tenant_id}/configuration/{target}",
            proposed_arguments={"old_field": old_field, "new_field": new_field},
            validation_actions=(f"validate {target} against {new_field}",),
            rollback_actions=(f"restore {target} mapping to {old_field}",),
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            confidence=0.94,
            evidence_refs=(configuration_ref, "catalog-dependencies"),
            unknowns=(),
        )
    outputs["verification"] = VerificationProposal(
        tenant_id=event.tenant_id,
        change_id=request.change_id,
        checks=(
            "run customer API contract suite",
            "run CRM synchronization test",
            "run analytics data-quality validation",
            "run support lookup test",
            "check audit completeness",
        ),
        partial_result_handling=(
            "Report partial and stop completion until every required check passes."
        ),
        failure_handling="Request deterministic rollback; do not remediate directly.",
        evidence_refs=evidence_refs,
        confidence=0.93,
    )
    return outputs


def _compliance_output(
    request: FleetAnalysisRequest, policy_evidence: EvidenceItem
) -> ComplianceAnalysis:
    policy = policy_evidence.attributes
    return ComplianceAnalysis(
        tenant_id=request.event.tenant_id,
        change_id=request.change_id,
        applicable_policy_ids=(_required_string(policy["policy_id"]),),
        required_approvals=_required_string_tuple(policy["required_approvals"]),
        required_evidence=_required_string_tuple(policy["required_evidence"]),
        forbidden_actions=_required_string_tuple(policy["forbidden_actions"]),
        retention_requirements=_required_string_tuple(policy["retention_requirements"]),
        missing_policy_data=("tenant-specific change window is not yet available",),
        evidence_refs=(policy_evidence.evidence_id,),
        confidence=0.87,
    )


def _required_string(value: JsonValue) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected a non-empty evidence string")
    return value


def _required_string_tuple(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected an evidence list containing only strings")
    return cast(tuple[str, ...], tuple(value))


def _response_for(output: BaseModel) -> Any:
    def responder() -> BaseModel:
        return output

    return responder


def _dependency_paths(source: str, graph: dict[str, list[str]]) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []
    queue: deque[tuple[str, ...]] = deque([(source,)])
    while queue:
        path = queue.popleft()
        children = graph.get(path[-1], [])
        if not children and len(path) > 1:
            paths.append(path)
        for child in children:
            if child not in path:
                queue.append((*path, child))
    return tuple(paths)


def _build_plan(
    request: FleetAnalysisRequest,
    proposals: tuple[RemediationProposal, ...],
    evidence: tuple[EvidenceItem, ...],
) -> RemediationPlan:
    old_field, _ = field_transition(request.event)
    steps = tuple(
        RemediationStep(
            step_id=f"step-{index}-{proposal.agent_id}",
            order=index,
            agent_id=proposal.agent_id,
            tool_name=proposal.proposed_tool,
            resource=proposal.target_resource,
            arguments=proposal.proposed_arguments,
            depends_on=(),
            risk_level=proposal.risk_level,
            requires_approval=True,
            idempotency_key=f"{request.change_id}:{proposal.agent_id}:{old_field}",
        )
        for index, proposal in enumerate(proposals, start=1)
    )
    return RemediationPlan(
        plan_id=f"plan_{uuid5(NAMESPACE_URL, request.change_id).hex}",
        tenant_id=request.event.tenant_id,
        change_id=request.change_id,
        version=1,
        risk_level=RiskLevel.HIGH,
        summary="Draft only: three approval-gated sandbox mapping proposals.",
        preconditions=("policy evaluation passes", "plan hash is approved", "snapshots exist"),
        steps=steps,
        verification_steps=("execute the verification agent's five read-only checks",),
        rollback_steps=("restore every changed sandbox configuration from its bound snapshot",),
        evidence_refs=tuple(item.evidence_id for item in evidence),
        created_at=request.event.received_at,
    )


def _invocation_record(
    registration: AgentRegistration,
    output: Any,
    model: str | BaseLlm,
    tracker: InvocationTracker,
) -> AgentInvocationRecord:
    evidence_refs = tuple(output.evidence_refs)
    return AgentInvocationRecord(
        invocation_id=(
            f"invocation_{registration.agent_id}_"
            f"{uuid5(NAMESPACE_URL, registration.tenant_id).hex[:12]}"
        ),
        agent_id=registration.agent_id,
        identity_reference=registration.identity_reference,
        model_name=model_name(model),
        model_calls=tracker.calls.get(registration.agent_id, 1),
        tool_calls=0,
        started_at=tracker.started[registration.agent_id],
        completed_at=tracker.completed[registration.agent_id],
        output_hash=sha256_digest(output),
        evidence_refs=evidence_refs,
    )
