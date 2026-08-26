# ADR 0005: Contracts, state, and audit boundary

- Status: Accepted
- Date: 2026-08-26

## Context

Change plans become approval and execution authority later in the workflow. A
model-generated status, an ambiguous serialization, a stale writer, or a
tenant-unscoped lookup must therefore be unable to alter workflow state.
Rejected transitions must also remain observable instead of disappearing as
application errors.

## Decision

- Pydantic contracts are the authoritative runtime validation boundary. They
  are immutable, reject unknown fields, and require timezone-aware timestamps.
- The TypeScript package mirrors the wire names and enum values and is checked
  against the same golden remediation plan fixture.
- Plan hashes use UTF-8 canonical JSON with sorted object keys, compact
  separators, explicit nulls, finite numbers only, and a `sha256:` prefix.
- Workflow transitions use a static application-owned graph. Agents and model
  output cannot add, skip, or reinterpret transitions.
- Every successful state transition atomically commits its audit event through
  the repository protocol. Invalid and stale transitions append a rejected
  audit event before returning an error.
- Every repository operation requires an explicit `tenant_id`. A lookup for an
  identifier owned only by another tenant raises a scope violation; it is never
  converted into an unscoped fallback query.
- Integer record versions provide optimistic concurrency. The Phase 3
  Firestore adapter must preserve the same transition-and-audit transaction.

## Consequences

Approval hashes can be reproduced by supported Python and TypeScript runtimes,
state changes are interview- and audit-defensible, and local tests do not need
cloud credentials. Adding or changing a workflow state requires an explicit
contract and graph change plus tests. Normal tenant-facing APIs may later map a
scope violation to a non-enumerating HTTP response, while preserving the
internal security distinction and audit behavior.
