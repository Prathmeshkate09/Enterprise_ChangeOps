import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  revalidatePath: vi.fn(),
  startDemoWorkflow: vi.fn(),
  submitApprovalDecision: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock("@/lib/changeops-data", () => ({
  isValidIdentifier: (value: string) => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value),
  safeActionError: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
  startDemoWorkflow: mocks.startDemoWorkflow,
  submitApprovalDecision: mocks.submitApprovalDecision,
}));

import { createDemoChangeAction, decideApprovalAction } from "./actions";

const IDLE = { status: "idle" as const, message: "" };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Control Tower server actions", () => {
  it("rejects an invalid tenant before publishing a demo event", async () => {
    const form = new FormData();
    form.set("tenantId", "../cross-tenant");

    await expect(createDemoChangeAction(IDLE, form)).resolves.toEqual({
      status: "error",
      message: "Enter a valid tenant identifier.",
    });
    expect(mocks.startDemoWorkflow).not.toHaveBeenCalled();
  });

  it("returns only safe navigation data after the gateway accepts an event", async () => {
    mocks.startDemoWorkflow.mockResolvedValue({ changeId: "chg_demo" });
    const form = new FormData();
    form.set("tenantId", "tenant_demo");

    await expect(createDemoChangeAction(IDLE, form)).resolves.toEqual({
      status: "success",
      message: "Sandbox workflow is durable. Deterministic analysis is running.",
      tenantId: "tenant_demo",
      changeId: "chg_demo",
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/");
  });

  it("validates the approval decision before calling the governed gateway", async () => {
    const form = new FormData();
    form.set("tenantId", "tenant_demo");
    form.set("approvalId", "approval_demo");
    form.set("expectedVersion", "1");
    form.set("decision", "override-policy");
    form.set("comment", "Evidence reviewed.");

    await expect(decideApprovalAction(IDLE, form)).resolves.toEqual({
      status: "error",
      message: "Approval decision is invalid.",
    });
    expect(mocks.submitApprovalDecision).not.toHaveBeenCalled();
  });
});
