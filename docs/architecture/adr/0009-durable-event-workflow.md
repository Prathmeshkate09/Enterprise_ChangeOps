# ADR 0009: Durable event workflow and compensation

- Status: Accepted
- Date: 2026-08-28

## Context

The governed Tool Gateway can execute one exact approved step safely, but the
platform also needs durable event ingestion, a restart-safe human approval
pause, bounded retries, dependency-aware execution, independent verification,
and compensation across multiple systems. Pub/Sub delivery is at least once,
so the workflow must remain correct when a message or callback is repeated.

## Decision

- The Event Gateway authenticates the exact webhook bytes, validates the
  versioned event contract and request limits, and creates a tenant-scoped
  Firestore inbox record before publishing the normalized event to Pub/Sub.
- Event identity is canonical over tenant, source type, and source event ID.
  A repeated identical event returns the stored result; different content at
  the same identity fails with a conflict.
- The Workflow Coordinator owns a tenant- and change-scoped Firestore record.
  The deterministic event-derived workflow ID makes Pub/Sub redelivery and
  service restart recovery converge on one execution.
- Approval creation and decisions are idempotent for the exact request. A
  decision is stored and audited before an authenticated callback resumes the
  workflow. Callback delivery failure is returned as retryable instead of
  being treated as success.
- Every pre-write snapshot ID and canonical configuration hash is persisted
  before mutation. Ready DAG steps run concurrently only when every dependency
  has succeeded, and all writes continue to pass through the Tool Gateway.
- Network, rate-limit, and temporary downstream failures use bounded
  exponential backoff with jitter. Validation, policy, authorization, approval,
  and other permanent failures are not retried indefinitely and are recorded
  once in the dead-letter collection and Pub/Sub dead-letter topic.
- CRM, Analytics, and Support verification runs independently. A critical
  failure moves the change to `ROLLING_BACK`, restores snapshots in reverse
  plan order, verifies the restored hashes, and ends as `FAILED` or
  `NEEDS_ATTENTION` without discarding execution evidence.
- Local development uses the official Pub/Sub and Firestore emulators plus the
  application-owned workflow runtime. It reproduces delivery, restart,
  callback, retry, DLQ, and compensation semantics without cloud credentials.

## Consequences

The local golden workflow survives a coordinator restart and duplicate event,
retries one injected Analytics failure, and completes three governed writes.
A controlled Support verification failure restores every bound snapshot, and
an unsupported event dead-letters once without a retry loop. Managed Cloud
Workflows callback IAM and deployment remain a cloud verification boundary;
the local gate does not claim they were exercised.
