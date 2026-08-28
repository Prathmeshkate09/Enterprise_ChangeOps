# ADR 0010: Control Tower server boundary and sandbox actions

- Status: Accepted
- Date: 2026-08-29

## Context

Operators need one responsive view of tenant changes, durable workflow state,
agent limits, exact-plan approvals, security controls, dead letters, and audit
evidence. Browser code must not receive shared service credentials or gain a
generic path to internal APIs, and unavailable evidence must not be presented
as success.

## Decision

- The Next.js Control Tower uses a server-only data-access layer as its backend
  for frontend. Internal service URLs, webhook signing material, and the local
  HMAC operator identity never cross the server/client serialization boundary.
- Reads are tenant-scoped, uncached, bounded by timeouts, and performed in
  parallel where independent. Each unavailable source becomes a visible
  service issue rather than fabricated empty success.
- The browser receives only the typed operational data needed to render each
  section. Approval client components receive primitive scope and version
  fields, not credentials or a caller-selectable endpoint.
- Golden-change and approval mutations are server actions. They are enabled
  only when the environment is explicitly `sandbox`, sandbox actions are
  explicitly enabled, and `PRODUCTION_WRITES_ENABLED` is exactly `false`.
- A golden-change action signs the exact event bytes and waits until the
  asynchronous event has a durable Control API projection before navigating.
  Unsupported events and projection timeouts remain explicit failures.
- Live updates use a tenant- and change-scoped same-origin route that proxies
  the Control API SSE stream and preserves `Last-Event-ID` for resumable audit
  delivery. Terminal workflows close their browser stream.

## Consequences

The local operator can start and approve the golden sandbox workflow without
seeing or supplying service secrets, then follow measured execution and audit
evidence to completion. The Phase 7 gate also verifies server-rendered waiting
and completed states. Managed user authentication, production deployment, and
production write enablement remain outside this decision and are not implied by
the local sandbox identity.
