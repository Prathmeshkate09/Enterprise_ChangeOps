# Tool Gateway

Phase 5 security boundary for authenticated identity, tenant scope, registered
tools, deterministic policy and risk, exact-plan approval, concurrency quotas,
transactional idempotency reservation, typed execution, and audit enforcement.

The internal execution endpoint accepts only short-lived authenticated agent
identities and never accepts caller-selected URLs or connection details. The
local HMAC identity adapter requires `TOOL_GATEWAY_AUTH_SECRET` with at least 32
random bytes and `AUTH_AUDIENCE`. Managed workload/agent identity replaces this
adapter in Phase 8.

All executable tools target the disclosed CRM, Analytics, or Support sandbox.
Production writes remain impossible.
