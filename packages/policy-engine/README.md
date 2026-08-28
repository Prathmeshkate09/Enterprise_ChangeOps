# Policy engine

Fail-closed Phase 5 policy evaluation for governed tool execution. It compares
verified identity, tenant, authoritative workflow state, canonical plan hash,
exact step arguments, registered tool ownership, resource scope, environment,
risk, and current approval before returning an allow decision.

The package is deterministic and has no model or network dependency. Critical
risk and non-sandbox mutations are denied in this build.
