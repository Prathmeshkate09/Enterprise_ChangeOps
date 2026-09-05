"use server";

import "server-only";

import { revalidatePath } from "next/cache";

import {
  isValidIdentifier,
  safeActionError,
  startDemoWorkflow,
  submitApprovalDecision,
} from "@/lib/changeops-data";
import type { ActionState } from "@/lib/changeops-types";
import { enterpriseEnabled } from "@/lib/enterprise-access";

function formString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function createDemoChangeAction(
  _previousState: ActionState,
  formData: FormData,
): Promise<ActionState> {
  if (enterpriseEnabled()) return { status: "error", message: "Sandbox actions are unavailable in enterprise mode." };
  const tenantId = formString(formData, "tenantId");
  if (!isValidIdentifier(tenantId)) {
    return { status: "error", message: "Enter a valid tenant identifier." };
  }
  try {
    const result = await startDemoWorkflow(tenantId);
    revalidatePath("/");
    return {
      status: "success",
      message: "Sandbox workflow is durable. Deterministic analysis is running.",
      tenantId,
      changeId: result.changeId,
    };
  } catch (error) {
    console.error("control_tower_demo_action_failed", { tenantId, error });
    return {
      status: "error",
      message: safeActionError(error, "The sandbox workflow could not be started."),
    };
  }
}

export async function decideApprovalAction(
  _previousState: ActionState,
  formData: FormData,
): Promise<ActionState> {
  if (enterpriseEnabled()) return { status: "error", message: "Sandbox actions are unavailable in enterprise mode." };
  const tenantId = formString(formData, "tenantId");
  const approvalId = formString(formData, "approvalId");
  const comment = formString(formData, "comment");
  const decision = formString(formData, "decision");
  const expectedVersion = Number(formString(formData, "expectedVersion"));
  if (!isValidIdentifier(tenantId) || !isValidIdentifier(approvalId)) {
    return { status: "error", message: "Approval scope is invalid." };
  }
  if (!(["approve", "reject", "request-changes"] as const).includes(
    decision as "approve" | "reject" | "request-changes",
  )) {
    return { status: "error", message: "Approval decision is invalid." };
  }
  try {
    await submitApprovalDecision({
      tenantId,
      approvalId,
      expectedVersion,
      decision: decision as "approve" | "reject" | "request-changes",
      comment,
    });
    revalidatePath("/");
    return {
      status: "success",
      message: "Decision recorded and workflow callback delivered.",
    };
  } catch (error) {
    console.error("control_tower_approval_action_failed", { tenantId, approvalId, error });
    return {
      status: "error",
      message: safeActionError(error, "The approval decision could not be recorded."),
    };
  }
}
