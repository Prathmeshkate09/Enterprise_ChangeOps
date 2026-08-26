# ADR 0007: Firestore control API and resumable audit

- Status: Accepted
- Date: 2026-08-26

## Context

Operational change state must survive a Control API restart, tenant audit must
be queryable without scanning other tenants, and clients must recover an event
stream without duplicating the last processed audit event. The existing
repository contract already requires optimistic versions and atomic state and
audit behavior, but the Phase 1 memory adapter is process local.

## Decision

- Firestore is authoritative for operational state when
  `PERSISTENCE_BACKEND=firestore`; the memory adapter remains available for
  deterministic unit tests and native local development.
- Changes live at `tenants/{tenant_id}/changes/{change_id}`. Per-change audit
  lives below each change, and an audit document is mirrored into
  `tenants/{tenant_id}/audit_index` for tenant-wide listing.
- Change creation, successful transitions, rejected-operation audit, and both
  audit copies use Firestore transactions. Record versions enforce optimistic
  concurrency, and Firestore server timestamps establish persisted event time.
- Every Firestore path is built from validated document identifiers and every
  query begins at an explicit tenant document. No operational API performs a
  collection-group or global tenant scan.
- The Control API validates tenant, actor, request, and cursor inputs and maps
  known persistence failures to stable, non-enumerating HTTP errors. Readiness
  fails with 503 when the selected repository cannot be reached.
- SSE event IDs are audit-event IDs. A valid `Last-Event-ID` is resolved inside
  the tenant and change before response streaming begins; subsequent events
  are ordered by server timestamp and document ID and start strictly after the
  cursor. A bounded `follow=false` catch-up mode supports deterministic gates.
- Local Compose uses the pinned official Google Cloud CLI emulator image. The
  emulator is not durable after the emulator container is removed; the restart
  gate deliberately restarts only the Control API while Firestore remains up.
- `X-Tenant-ID` and `X-Actor-ID` are validated request context, not
  authentication. Phase 5 must bind them to verified identity and policy.

## Consequences

The Control API can restart without losing workflow state, and stream clients
can resume without replaying their cursor event. The tenant audit index costs
an additional transactional write but avoids cross-tenant scans and keeps
tenant-wide audit access explicit. A managed deployment still requires an
approved Google Cloud project, database, credentials, indexes, and security
rules; the local emulator gate does not claim those cloud controls are live.
