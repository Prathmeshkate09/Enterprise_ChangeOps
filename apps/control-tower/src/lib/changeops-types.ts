export type JsonValue =
  | boolean
  | number
  | string
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ActionState = Readonly<{
  status: "idle" | "success" | "error";
  message: string;
  tenantId?: string;
  changeId?: string;
}>;

export type ControlTowerAction = (
  previousState: ActionState,
  formData: FormData,
) => Promise<ActionState>;

export type ChangeRecord = Readonly<{
  change_id: string;
  tenant_id: string;
  event_id: string;
  change_type: string;
  title: string;
  description: string;
  source: Readonly<{ type: string; external_id: string; url: string }>;
  environment: "local" | "test" | "sandbox";
  status: string;
  risk_level: string;
  current_phase: string;
  workflow_execution_id: string | null;
  plan_version: number;
  plan_hash: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  version: number;
}>;

export type AuditEvent = Readonly<{
  audit_event_id: string;
  tenant_id: string;
  change_id: string;
  trace_id: string;
  event_type: string;
  actor_type: string;
  actor_id: string;
  resource: string;
  action: string;
  decision_id: string | null;
  input_hash: string;
  output_hash: string;
  status: "success" | "rejected" | "failure";
  redacted_summary: string;
  created_at: string;
}>;

export type RemediationStep = Readonly<{
  step_id: string;
  order: number;
  agent_id: string;
  tool_name: string;
  resource: string;
  arguments: Readonly<Record<string, JsonValue>>;
  depends_on: readonly string[];
  risk_level: string;
  requires_approval: boolean;
  idempotency_key: string;
}>;

export type RemediationPlan = Readonly<{
  plan_id: string;
  tenant_id: string;
  change_id: string;
  version: number;
  risk_level: string;
  summary: string;
  preconditions: readonly string[];
  steps: readonly RemediationStep[];
  verification_steps: readonly string[];
  rollback_steps: readonly string[];
  evidence_refs: readonly string[];
  created_at: string;
}>;

export type WorkflowTask = Readonly<{
  step_id: string;
  system_id: "crm" | "analytics" | "support";
  status: string;
  attempt_count: number;
  snapshot_id: string | null;
  snapshot_hash: string | null;
  execution_id: string | null;
  output_hash: string | null;
  error_code: string | null;
  updated_at: string;
}>;

export type WorkflowExecution = Readonly<{
  workflow_execution_id: string;
  tenant_id: string;
  change_id: string;
  event_id: string;
  trace_id: string;
  event: Readonly<{
    event_type: string;
    occurred_at: string;
    subject: Readonly<{
      system_id: string;
      resource_type: string;
      resource_id: string;
    }>;
    change: Readonly<{
      summary: string;
      old_version: string;
      new_version: string;
      artifact_refs: readonly string[];
    }>;
  }>;
  status: string;
  delivery_attempts: number;
  plan: RemediationPlan | null;
  plan_hash: string | null;
  approval_id: string | null;
  approval_expires_at: string | null;
  tasks: readonly WorkflowTask[];
  last_error_code: string | null;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  version: number;
}>;

export type ApprovalRequest = Readonly<{
  approval_id: string;
  tenant_id: string;
  change_id: string;
  plan_id: string;
  plan_hash: string;
  plan_version: number;
  environment: string;
  scope: readonly string[];
  status: "PENDING" | "APPROVED" | "REJECTED" | "CHANGES_REQUESTED";
  requested_by: string;
  requested_at: string;
  expires_at: string;
  decided_by: string | null;
  decided_by_roles: readonly string[];
  decided_at: string | null;
  comment: string | null;
  version: number;
}>;

export type AgentRegistration = Readonly<{
  agent_id: string;
  tenant_id: string;
  display_name: string;
  description: string;
  version: string;
  owner: string;
  capabilities: readonly string[];
  allowed_tools: readonly string[];
  allowed_resource_patterns: readonly string[];
  risk_ceiling: string;
  runtime_endpoint: string;
  identity_reference: string;
  status: string;
  budget: Readonly<{
    max_model_calls: number;
    max_tool_calls: number;
    max_turns: number;
    timeout_seconds: number;
  }>;
  created_at: string;
  updated_at: string;
}>;

export type ToolRegistration = Readonly<{
  tool_name: string;
  owning_agent_id: string;
  action: string;
  resource_pattern: string;
  risk_level: string;
  mutating: boolean;
  allowed_environments: readonly string[];
  policy_ids: readonly string[];
  timeout_seconds: number;
}>;

export type DeadLetterRecord = Readonly<{
  dead_letter_id: string;
  tenant_id: string;
  event_id: string;
  workflow_execution_id: string;
  error_code: string;
  input_hash: string;
  created_at: string;
}>;

export type ServiceIssue = Readonly<{
  service: string;
  message: string;
}>;

export type DashboardData = Readonly<{
  tenantId: string;
  sandboxActionsEnabled: boolean;
  changes: readonly ChangeRecord[];
  selectedChange: ChangeRecord | null;
  workflow: WorkflowExecution | null;
  approvals: readonly ApprovalRequest[];
  agents: readonly AgentRegistration[];
  tools: readonly ToolRegistration[];
  audit: readonly AuditEvent[];
  deadLetters: readonly DeadLetterRecord[];
  issues: readonly ServiceIssue[];
}>;
