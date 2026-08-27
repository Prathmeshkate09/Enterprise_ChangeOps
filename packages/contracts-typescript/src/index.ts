export const RISK_LEVELS = ["unknown", "low", "medium", "high", "critical"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

export const CHANGE_ENVIRONMENTS = ["local", "test", "sandbox"] as const;
export type ChangeEnvironment = (typeof CHANGE_ENVIRONMENTS)[number];

export const WORKFLOW_STATES = [
  "RECEIVED",
  "SCREENING",
  "BLOCKED",
  "ANALYZING",
  "PLAN_READY",
  "AWAITING_APPROVAL",
  "APPROVED",
  "REJECTED",
  "EXECUTING",
  "VERIFYING",
  "ROLLING_BACK",
  "COMPLETED",
  "FAILED",
  "PARTIAL",
  "CANCELLED",
  "NEEDS_ATTENTION",
] as const;
export type WorkflowState = (typeof WORKFLOW_STATES)[number];

export const POLICY_EFFECTS = [
  "ALLOW",
  "DENY",
  "REQUIRE_APPROVAL",
  "BLOCK_SECURITY",
  "RATE_LIMIT",
  "NEEDS_REVIEW",
] as const;
export type PolicyEffect = (typeof POLICY_EFFECTS)[number];

export type ApprovalDecision = "APPROVED" | "REJECTED";
export type ActorType = "user" | "agent" | "service" | "system";
export type AuditStatus = "success" | "rejected" | "failure";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | readonly JsonValue[] | JsonObject;
export interface JsonObject {
  readonly [key: string]: JsonValue;
}

export interface ChangeSource {
  readonly type: string;
  readonly external_id: string;
  readonly url: string;
}

export interface ChangeSubject {
  readonly system_id: string;
  readonly resource_type: string;
  readonly resource_id: string;
}

export interface ChangeDetails {
  readonly summary: string;
  readonly old_version: string;
  readonly new_version: string;
  readonly artifact_refs: readonly string[];
}

export interface ChangeEvent {
  readonly schema_version: "1.0";
  readonly event_id: string;
  readonly tenant_id: string;
  readonly event_type: string;
  readonly source: ChangeSource;
  readonly occurred_at: string;
  readonly received_at: string;
  readonly subject: ChangeSubject;
  readonly change: ChangeDetails;
  readonly correlation_id: string;
  readonly trace_id: string;
}

export interface ChangeRecord {
  readonly change_id: string;
  readonly tenant_id: string;
  readonly event_id: string;
  readonly change_type: string;
  readonly title: string;
  readonly description: string;
  readonly source: ChangeSource;
  readonly environment: ChangeEnvironment;
  readonly status: WorkflowState;
  readonly risk_level: RiskLevel;
  readonly current_phase: WorkflowState;
  readonly workflow_execution_id: string | null;
  readonly plan_version: number;
  readonly plan_hash: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly created_by: string;
  readonly version: number;
}

export interface ImpactFinding {
  readonly finding_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly system_id: string;
  readonly finding_type: string;
  readonly severity: RiskLevel;
  readonly confidence: number;
  readonly summary: string;
  readonly evidence_refs: readonly string[];
  readonly owner_refs: readonly string[];
  readonly recommended_actions: readonly string[];
  readonly created_by_agent: string;
  readonly created_at: string;
}

export interface RemediationStep {
  readonly step_id: string;
  readonly order: number;
  readonly agent_id: string;
  readonly tool_name: string;
  readonly resource: string;
  readonly depends_on: readonly string[];
  readonly risk_level: RiskLevel;
  readonly requires_approval: boolean;
  readonly idempotency_key: string;
}

export interface RemediationPlan {
  readonly plan_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly version: number;
  readonly risk_level: RiskLevel;
  readonly summary: string;
  readonly preconditions: readonly string[];
  readonly steps: readonly RemediationStep[];
  readonly verification_steps: readonly string[];
  readonly rollback_steps: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly created_at: string;
}

export interface ToolIntent {
  readonly schema_version: "1.0";
  readonly intent_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly workflow_execution_id: string;
  readonly plan_id: string;
  readonly plan_hash: string;
  readonly step_id: string;
  readonly agent_identity: string;
  readonly tool_name: string;
  readonly action: string;
  readonly resource: string;
  readonly arguments: JsonObject;
  readonly reason: string;
  readonly evidence_refs: readonly string[];
  readonly idempotency_key: string;
  readonly requested_at: string;
}

export interface PolicyDecision {
  readonly decision_id: string;
  readonly tenant_id: string;
  readonly intent_id: string;
  readonly effect: PolicyEffect;
  readonly computed_risk: RiskLevel;
  readonly approval_required: boolean;
  readonly approval_valid: boolean;
  readonly matched_policy_ids: readonly string[];
  readonly reasons: readonly string[];
  readonly evaluated_at: string;
}

export interface Approval {
  readonly approval_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly plan_id: string;
  readonly plan_hash: string;
  readonly decision: ApprovalDecision;
  readonly scope: readonly string[];
  readonly approved_by: string;
  readonly approved_at: string;
  readonly expires_at: string;
  readonly comment: string;
}

export interface AuditEvent {
  readonly audit_event_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly trace_id: string;
  readonly event_type: string;
  readonly actor_type: ActorType;
  readonly actor_id: string;
  readonly resource: string;
  readonly action: string;
  readonly decision_id: string | null;
  readonly input_hash: string;
  readonly output_hash: string;
  readonly status: AuditStatus;
  readonly redacted_summary: string;
  readonly created_at: string;
}

export type AgentStatus = "active" | "disabled";
export type EvidenceTrust = "platform" | "untrusted";

export interface AgentInvocationBudget {
  readonly max_model_calls: number;
  readonly max_tool_calls: number;
  readonly max_turns: number;
  readonly timeout_seconds: number;
}

export interface AgentRegistration {
  readonly agent_id: string;
  readonly tenant_id: string;
  readonly display_name: string;
  readonly description: string;
  readonly version: string;
  readonly owner: string;
  readonly capabilities: readonly string[];
  readonly allowed_tools: readonly string[];
  readonly allowed_resource_patterns: readonly string[];
  readonly risk_ceiling: RiskLevel;
  readonly runtime_endpoint: string;
  readonly identity_reference: string;
  readonly status: AgentStatus;
  readonly budget: AgentInvocationBudget;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface EvidenceItem {
  readonly evidence_id: string;
  readonly tenant_id: string;
  readonly source_system: string;
  readonly source_resource: string;
  readonly summary: string;
  readonly content_hash: string;
  readonly trust: EvidenceTrust;
  readonly observed_at: string;
  readonly attributes: JsonObject;
}

export interface DependencyPath {
  readonly systems: readonly string[];
  readonly evidence_refs: readonly string[];
}

export interface OrchestrationDirective {
  readonly tenant_id: string;
  readonly change_id: string;
  readonly normalized_objective: string;
  readonly selected_agent_ids: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly confidence: number;
  readonly unknowns: readonly string[];
}

export interface ImpactAnalysis {
  readonly tenant_id: string;
  readonly change_id: string;
  readonly affected_systems: readonly string[];
  readonly dependency_paths: readonly DependencyPath[];
  readonly severity: RiskLevel;
  readonly confidence: number;
  readonly evidence_refs: readonly string[];
  readonly owner_refs: readonly string[];
  readonly unknowns: readonly string[];
}

export interface ComplianceAnalysis {
  readonly tenant_id: string;
  readonly change_id: string;
  readonly applicable_policy_ids: readonly string[];
  readonly required_approvals: readonly string[];
  readonly required_evidence: readonly string[];
  readonly forbidden_actions: readonly string[];
  readonly retention_requirements: readonly string[];
  readonly missing_policy_data: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly confidence: number;
}

export interface RemediationProposal {
  readonly proposal_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly agent_id: string;
  readonly target_system: string;
  readonly summary: string;
  readonly proposed_tool: string;
  readonly target_resource: string;
  readonly proposed_arguments: JsonObject;
  readonly validation_actions: readonly string[];
  readonly rollback_actions: readonly string[];
  readonly risk_level: RiskLevel;
  readonly requires_approval: boolean;
  readonly confidence: number;
  readonly evidence_refs: readonly string[];
  readonly unknowns: readonly string[];
}

export interface VerificationProposal {
  readonly tenant_id: string;
  readonly change_id: string;
  readonly checks: readonly string[];
  readonly partial_result_handling: string;
  readonly failure_handling: string;
  readonly evidence_refs: readonly string[];
  readonly confidence: number;
}

export interface AgentInvocationRecord {
  readonly invocation_id: string;
  readonly agent_id: string;
  readonly identity_reference: string;
  readonly model_name: string;
  readonly model_calls: number;
  readonly tool_calls: number;
  readonly started_at: string;
  readonly completed_at: string;
  readonly output_hash: string;
  readonly evidence_refs: readonly string[];
}

export interface FleetAnalysisRequest {
  readonly change_id: string;
  readonly event: ChangeEvent;
}

export interface FleetAnalysisResult {
  readonly analysis_id: string;
  readonly tenant_id: string;
  readonly change_id: string;
  readonly trace_id: string;
  readonly model_mode: "fake" | "live";
  readonly orchestration: OrchestrationDirective;
  readonly impact: ImpactAnalysis;
  readonly compliance: ComplianceAnalysis;
  readonly remediation_proposals: readonly RemediationProposal[];
  readonly verification: VerificationProposal;
  readonly draft_plan: RemediationPlan;
  readonly draft_plan_hash: string;
  readonly evidence: readonly EvidenceItem[];
  readonly invocations: readonly AgentInvocationRecord[];
  readonly max_parallel_agents: number;
  readonly started_at: string;
  readonly completed_at: string;
}

export function isWorkflowState(value: string): value is WorkflowState {
  return (WORKFLOW_STATES as readonly string[]).includes(value);
}

export function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("Canonical JSON does not support non-finite numbers.");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }

  const record = value as Readonly<Record<string, JsonValue>>;
  const entries = Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key] as JsonValue)}`);
  return `{${entries.join(",")}}`;
}

export function canonicalPlanJson(plan: RemediationPlan): string {
  return canonicalJson(plan as unknown as JsonValue);
}
