# ADR 0012: Private managed runtime foundation

## Status

Accepted for Phase 9.

## Context

Phase 8 proved the managed governance adapters but left the deterministic control plane,
workflow, tool boundary, UI, and enterprise sandboxes local. Cloud Run rejects unauthenticated
requests before application-level HMAC authentication, so callers need platform identity without
overwriting the existing application `Authorization` header.

## Decision

- Deploy all runtime services to Cloud Run with unauthenticated access disabled and a distinct
  user-managed service account for each service.
- Call private services with a Google-signed ID token whose audience is the destination service
  origin. Put that token in `X-Serverless-Authorization`; preserve application bearer tokens and
  callback/webhook signatures in their existing headers.
- Keep deterministic workflow, approval, policy, retry, audit, and tool execution in application
  code. Managed identity authenticates transport; it does not replace application authorization.
- Use Firestore for durable control, inbox, workflow, idempotency, and audit state. Runtime
  identities may verify but may not create Pub/Sub infrastructure.
- Keep the pull-based Workflow Coordinator at exactly one always-allocated instance. This is a
  managed-sandbox constraint until the subscriber is replaced by a request-driven consumer.
- Keep one Event Gateway instance warm so an accepted, state-changing event request cannot outlive
  the Control Tower request timeout during a cold start.
- Keep each in-memory synthetic enterprise sandbox at one instance so a demonstration has stable
  state. Their data remains explicitly synthetic and can reset on a revision restart.
- Keep Control Tower private. Operators access it with an authenticated Cloud Run proxy.
- Keep `PRODUCTION_WRITES_ENABLED=false`; Phase 9 does not authorize real enterprise mutations.
- Build deployable images with Cloud Build. Automating deployment from GitHub with Workload
  Identity Federation is a later delivery step after this runtime gate is proven.

## Consequences

The managed runtime has no public endpoint and stores no service-account keys. Internal calls fail
closed when Google identity-token acquisition fails. The always-on event, workflow, and sandbox
instances create a small continuing sandbox cost. A restart can reset synthetic sandbox state, while durable
workflow and audit records remain in Firestore.
