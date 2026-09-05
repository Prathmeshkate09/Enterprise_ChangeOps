"use client";

import { useActionState, type ReactNode } from "react";
import type { FormResult } from "@/app/access-actions";

export function AccessForm({
  action,
  children,
  submit,
}: {
  action: (state: FormResult, form: FormData) => Promise<FormResult>;
  children: ReactNode;
  submit: string;
}) {
  const [state, formAction, pending] = useActionState(action, { message: "" });
  return (
    <form className="access-form" action={formAction}>
      {children}
      <button className="access-button" disabled={pending}>
        {pending ? "Saving…" : submit}
      </button>
      {state.message && (
        <p
          role="status"
          className={state.ok ? "access-success" : "access-notice"}
        >
          {state.message}
        </p>
      )}
      {state.token && (
        <div className="access-code">
          <strong>Invitation code · shown once</strong>
          <code>{state.token}</code>
        </div>
      )}
    </form>
  );
}
