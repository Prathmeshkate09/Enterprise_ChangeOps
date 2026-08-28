"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import type { ActionState, ControlTowerAction } from "@/lib/changeops-types";

const INITIAL_STATE: ActionState = { status: "idle", message: "" };

type DemoChangeFormProps = Readonly<{
  tenantId: string;
  enabled: boolean;
  action: ControlTowerAction;
}>;

export function DemoChangeForm({ tenantId, enabled, action }: DemoChangeFormProps) {
  const router = useRouter();
  const [state, formAction, pending] = useActionState(action, INITIAL_STATE);

  useEffect(() => {
    if (state.status === "success" && state.tenantId && state.changeId) {
      const query = new URLSearchParams({ tenant_id: state.tenantId, change_id: state.changeId });
      router.push(`/?${query.toString()}`);
    }
  }, [router, state]);

  return (
    <form action={formAction} className="demo-form">
      <input name="tenantId" type="hidden" value={tenantId} />
      <button className="button button-primary" disabled={!enabled || pending} type="submit">
        <span aria-hidden="true">＋</span>
        {pending ? "Starting workflow…" : "Run golden change"}
      </button>
      {state.message ? (
        <p className={`form-message form-message-${state.status}`} aria-live="polite">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
