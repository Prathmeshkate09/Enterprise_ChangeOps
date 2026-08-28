"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import type { ActionState, ControlTowerAction } from "@/lib/changeops-types";

const INITIAL_STATE: ActionState = { status: "idle", message: "" };

type ApprovalDecisionFormProps = Readonly<{
  tenantId: string;
  approvalId: string;
  expectedVersion: number;
  enabled: boolean;
  action: ControlTowerAction;
}>;

export function ApprovalDecisionForm({
  tenantId,
  approvalId,
  expectedVersion,
  enabled,
  action,
}: ApprovalDecisionFormProps) {
  const router = useRouter();
  const [state, formAction, pending] = useActionState(action, INITIAL_STATE);

  useEffect(() => {
    if (state.status === "success") router.refresh();
  }, [router, state.status]);

  return (
    <form action={formAction} className="approval-form">
      <input name="tenantId" type="hidden" value={tenantId} />
      <input name="approvalId" type="hidden" value={approvalId} />
      <input name="expectedVersion" type="hidden" value={expectedVersion} />
      <label htmlFor={`comment-${approvalId}`}>Decision rationale</label>
      <textarea
        id={`comment-${approvalId}`}
        maxLength={512}
        minLength={2}
        name="comment"
        placeholder="Reference the evidence and explain the decision."
        required
        rows={3}
      />
      <div className="approval-actions">
        <button
          className="button button-primary"
          disabled={!enabled || pending}
          name="decision"
          type="submit"
          value="approve"
        >
          {pending ? "Recording…" : "Approve exact plan"}
        </button>
        <button
          className="button button-secondary"
          disabled={!enabled || pending}
          name="decision"
          type="submit"
          value="request-changes"
        >
          Request changes
        </button>
        <button
          className="button button-danger"
          disabled={!enabled || pending}
          name="decision"
          type="submit"
          value="reject"
        >
          Reject
        </button>
      </div>
      {state.message ? (
        <p className={`form-message form-message-${state.status}`} aria-live="polite">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
