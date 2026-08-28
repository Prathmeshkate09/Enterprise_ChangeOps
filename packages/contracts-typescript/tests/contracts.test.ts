import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  WORKFLOW_STATES,
  canonicalPlanJson,
  isWorkflowState,
  type RemediationPlan,
} from "../src/index.js";
import { calculatePlanHash } from "../src/node.js";

const plan = {
  plan_id: "plan_001",
  tenant_id: "tenant_demo",
  change_id: "chg_001",
  version: 1,
  risk_level: "high",
  summary: "Update identifier mappings in CRM, analytics, and support.",
  preconditions: [
    "sandbox environment is healthy",
    "configuration snapshots are available",
  ],
  steps: [
    {
      step_id: "step_crm_001",
      order: 1,
      agent_id: "crm-agent-v1",
      tool_name: "crm.update_field_mapping",
      resource: "crm/customer-sync",
      arguments: {
        old_field: "customer_id",
        new_field: "customer_uuid",
      },
      depends_on: [],
      risk_level: "high",
      requires_approval: true,
      idempotency_key: "chg_001:crm:update-field-mapping",
    },
  ],
  verification_steps: ["verify.contract-suite", "verify.cross-system-data"],
  rollback_steps: ["restore.crm.snapshot", "restore.analytics.snapshot"],
  evidence_refs: ["evidence://impact/report/001"],
  created_at: "2026-08-27T10:37:30Z",
} as const satisfies RemediationPlan;

const sharedPlan = JSON.parse(
  readFileSync(
    new URL("../../contracts-fixtures/remediation-plan.json", import.meta.url),
    "utf8",
  ),
) as RemediationPlan;

describe("shared contracts", () => {
  it("publishes every specification workflow state", () => {
    expect(WORKFLOW_STATES).toHaveLength(16);
    expect(isWorkflowState("AWAITING_APPROVAL")).toBe(true);
    expect(isWorkflowState("MADE_UP_STATE")).toBe(false);
  });

  it("canonicalizes and hashes the same plan deterministically", () => {
    const canonical = canonicalPlanJson(plan);
    expect(canonical).toBe(canonicalPlanJson({ ...plan }));
    expect(canonical.startsWith('{"change_id":"chg_001"')).toBe(true);
    expect(calculatePlanHash(plan)).toMatch(/^sha256:[0-9a-f]{64}$/u);
    expect(calculatePlanHash(plan)).toBe(calculatePlanHash({ ...plan }));
    expect(calculatePlanHash(sharedPlan)).toBe(
      "sha256:dded9c4bd6aa11720533e36527293072e0f19b660b8e5dc59b5782224d830373",
    );
  });
});
