# ADR 0006: Functional enterprise sandbox boundary

- Status: Accepted
- Date: 2026-08-26

## Context

The golden workflow needs real enterprise-system behavior before the agent,
approval, and durable-workflow phases exist. Hardcoded successful responses
would hide retry, isolation, compensation, and verification failures. At the
same time, Phase 2 must not imply that its direct sandbox mutation endpoints
are the later authenticated tool gateway or an approval authority.

## Decision

- Customer API Registry, CRM, Analytics, and Support are independently
  deployable FastAPI services with versioned `/v1` JSON APIs and OpenAPI docs.
- Seed configurations and dependency edges are disclosed, versioned synthetic
  JSON resources. A reset creates a tenant-owned copy; runtime responses are
  derived from mutable service state.
- Every operational call requires `X-Tenant-ID`; middleware assigns or echoes
  `X-Request-ID`, and application and validation failures use stable envelopes.
- Snapshots include the owning tenant and a deterministic state hash. Restore
  rejects an unknown or cross-tenant snapshot.
- Mutation idempotency keys bind to the requested operation. Replaying the same
  operation returns its prior result; reusing a key for a different operation
  fails closed.
- Analytics can inject a bounded transient failure before mutation. A retry
  then succeeds once, and later replay does not increment state again.
- Verification is independently callable after mutation. CRM checks its sync
  source, Analytics compares the seeded row count and null rate, and Support
  checks its lookup field and dependent forms.
- The unmanaged order-service dependency remains a human-owned follow-up. No
  placeholder tool claims to mutate it.
- Direct Phase 2 mutation APIs are test-fixture boundaries, not approval or
  authorization boundaries. Phase 5 must place authenticated, plan-bound,
  policy-checked tool execution in front of them.

## Consequences

The migration can be exercised and compensated over real HTTP without cloud
credentials or fabricated outcomes. Service state is deliberately process
local and resets on restart; durable Firestore persistence belongs to Phase 3.
The sandbox proves behavior but must never be exposed as a production write
surface or treated as evidence that the later approval gateway already exists.
