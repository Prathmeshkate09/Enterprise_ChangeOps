# ADR 0008: Governed tool gateway

- Status: Accepted
- Date: 2026-08-28

## Context

The Phase 4 fleet can propose remediation, but model output must never grant
execution authority. A plan approval is meaningful only if it covers the exact
tool, resource, and mutation arguments that will be executed. Retried workflow
delivery must also be safe when the first execution result is lost.

## Decision

- Every remediation step contains its mutation arguments. The canonical plan
  hash therefore binds step ordering, ownership, tool, resource, arguments,
  risk, approval requirement, dependencies, rollback, and idempotency key.
- A separate Tool Gateway authenticates short-lived identities, loads the
  authoritative change and stored plan, evaluates deterministic policy, and
  executes only after an atomic idempotency reservation.
- The local identity adapter uses an audience-bound HMAC token with strict
  signature, issued-at, expiry, lifetime, tenant, subject, kind, and role
  validation. Phase 8 replaces this adapter with managed workload or agent
  identity; the authorization contract remains unchanged.
- The executable registry is closed. It contains only bounded CRM, Analytics,
  and Support field-mapping tools. Callers cannot supply URLs, connection
  details, SQL, shell commands, or unregistered tool implementations.
- Policy compares the verified caller, tenant, active workflow execution,
  `EXECUTING` state, environment, canonical plan and version, selected step,
  tool ownership, resource scope, exact arguments, idempotency key, and risk.
  Critical-risk and non-sandbox mutations fail closed.
- Mutations require a current approval for the exact plan hash, plan version,
  environment, and step. Only approver or platform-admin identities may decide
  requests, and the requester cannot approve their own request.
- In Firestore, governance records are stored below an explicit tenant and
  change. A tenant approval index supports tenant-scoped lookup without a
  collection-group or global scan. Approval decisions, idempotency
  reservations, executions, and mirrored audit evidence use transactions.
- A completed idempotency record returns the stored typed result. A different
  input using the same key conflicts. A bounded stale-reservation recovery path
  handles workers that disappear before persisting a result.
- Per-tenant, per-tool concurrency limits wrap reservation and execution so a
  rejected quota request cannot leave an abandoned execution reservation.

## Consequences

An approval cannot be reused after a plan change or to alter mutation
arguments, and duplicate delivery cannot create a second sandbox mutation.
The additional Firestore documents and transactions are deliberate costs for
durable authorization and audit evidence. Production execution remains
impossible because the registry and adapters expose sandbox endpoints only.
Managed identity, Model Armor, durable workflow callbacks, and cloud IAM remain
later-phase prerequisites and are not implied by the local gate.
