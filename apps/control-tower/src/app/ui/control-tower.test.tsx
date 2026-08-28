import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ActionState, DashboardData } from "@/lib/changeops-types";

import { ControlTower } from "./control-tower";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const NOW = "2026-08-28T12:00:00Z";
const HASH = `sha256:${"a".repeat(64)}`;

const data: DashboardData = {
  tenantId: "tenant_control_tower_demo",
  sandboxActionsEnabled: true,
  changes: [
    {
      change_id: "chg_demo",
      tenant_id: "tenant_control_tower_demo",
      event_id: "evt_demo",
      change_type: "api.breaking_change",
      title: "Rename customer_id to customer_uuid",
      description: "Golden customer API field migration.",
      source: { type: "github", external_id: "pr-demo", url: "https://example.invalid/demo" },
      environment: "sandbox",
      status: "COMPLETED",
      risk_level: "high",
      current_phase: "COMPLETED",
      workflow_execution_id: "wf_demo",
      plan_version: 1,
      plan_hash: HASH,
      created_at: NOW,
      updated_at: NOW,
      created_by: "workflow-coordinator",
      version: 7,
    },
  ],
  selectedChange: null,
  workflow: {
    workflow_execution_id: "wf_demo",
    tenant_id: "tenant_control_tower_demo",
    change_id: "chg_demo",
    event_id: "evt_demo",
    trace_id: "trace_demo",
    event: {
      event_type: "api.breaking_change",
      occurred_at: NOW,
      subject: { system_id: "customer-api", resource_type: "api-contract", resource_id: "v2" },
      change: {
        summary: "Rename customer_id to customer_uuid",
        old_version: "1.4.0",
        new_version: "2.0.0",
        artifact_refs: ["artifact://contract"],
      },
    },
    status: "COMPLETED",
    delivery_attempts: 1,
    plan: {
      plan_id: "plan_demo",
      tenant_id: "tenant_control_tower_demo",
      change_id: "chg_demo",
      version: 1,
      risk_level: "high",
      summary: "Migrate the bounded sandbox systems.",
      preconditions: ["approval"],
      steps: [
        {
          step_id: "crm_update",
          order: 1,
          agent_id: "crm",
          tool_name: "crm.patch_customer_field",
          resource: "crm://customer/schema",
          arguments: { old_field: "customer_id", new_field: "customer_uuid" },
          depends_on: [],
          risk_level: "high",
          requires_approval: true,
          idempotency_key: "idem_demo",
        },
      ],
      verification_steps: ["verify"],
      rollback_steps: ["restore"],
      evidence_refs: ["evidence_demo"],
      created_at: NOW,
    },
    plan_hash: HASH,
    approval_id: "approval_demo",
    approval_expires_at: NOW,
    tasks: [
      {
        step_id: "crm_update",
        system_id: "crm",
        status: "SUCCEEDED",
        attempt_count: 1,
        snapshot_id: "snapshot_demo",
        snapshot_hash: HASH,
        execution_id: "execution_demo",
        output_hash: HASH,
        error_code: null,
        updated_at: NOW,
      },
    ],
    last_error_code: null,
    started_at: NOW,
    updated_at: NOW,
    completed_at: NOW,
    version: 8,
  },
  approvals: [
    {
      approval_id: "approval_demo",
      tenant_id: "tenant_control_tower_demo",
      change_id: "chg_demo",
      plan_id: "plan_demo",
      plan_hash: HASH,
      plan_version: 1,
      environment: "sandbox",
      scope: ["crm_update"],
      status: "APPROVED",
      requested_by: "workflow-coordinator",
      requested_at: NOW,
      expires_at: "2026-08-28T13:00:00Z",
      decided_by: "control-tower-local-operator",
      decided_by_roles: ["APPROVER"],
      decided_at: NOW,
      comment: "Evidence reviewed.",
      version: 2,
    },
  ],
  agents: [
    {
      agent_id: "crm",
      tenant_id: "tenant_control_tower_demo",
      display_name: "CRM Remediation",
      description: "Creates a bounded CRM remediation proposal.",
      version: "1.0.0",
      owner: "platform",
      capabilities: ["crm analysis"],
      allowed_tools: ["crm.patch_customer_field"],
      allowed_resource_patterns: ["crm://customer/schema"],
      risk_ceiling: "high",
      runtime_endpoint: "http://agent-fleet:8200/agents/crm",
      identity_reference: "local://crm",
      status: "active",
      budget: { max_model_calls: 1, max_tool_calls: 0, max_turns: 1, timeout_seconds: 30 },
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  tools: [
    {
      tool_name: "crm.patch_customer_field",
      owning_agent_id: "crm",
      action: "patch",
      resource_pattern: "crm://customer/schema",
      risk_level: "high",
      mutating: true,
      allowed_environments: ["sandbox"],
      policy_ids: ["sandbox-only"],
      timeout_seconds: 5,
    },
  ],
  audit: [
    {
      audit_event_id: "audit_demo",
      tenant_id: "tenant_control_tower_demo",
      change_id: "chg_demo",
      trace_id: "trace_demo",
      event_type: "WORKFLOW_COMPLETED",
      actor_type: "service",
      actor_id: "workflow-coordinator",
      resource: "change/chg_demo",
      action: "transition",
      decision_id: null,
      input_hash: HASH,
      output_hash: HASH,
      status: "success",
      redacted_summary: "Workflow completed with verified sandbox mutations.",
      created_at: NOW,
    },
  ],
  deadLetters: [],
  issues: [],
};

const action = async (): Promise<ActionState> => ({ status: "idle", message: "" });

describe("Control Tower operational dashboard", () => {
  it("renders measured workflow, fleet, approval, security, and audit evidence", () => {
    render(
      <ControlTower
        createDemoAction={action}
        data={{ ...data, selectedChange: data.changes[0] ?? null }}
        decideApprovalAction={action}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Enterprise ChangeOps" })).toBeVisible();
    expect(screen.getByText("Production writes off")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Workflow execution" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "1 registered agents" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Approval workspace" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Security posture" })).toBeVisible();
    expect(screen.getByText("Workflow completed with verified sandbox mutations.")).toBeVisible();
    expect(screen.queryByText("Some operational evidence is unavailable")).not.toBeInTheDocument();
  });
});
