# Control API

The Control API is the tenant-facing deterministic boundary for operational
change state. It exposes change list/detail, per-change and tenant audit,
cancel/retry transitions, and resumable Server-Sent Events under `/v1`.

Every operational request requires `X-Tenant-ID`; mutations also require
`X-Actor-ID`. These headers are validated context in Phase 3, not proof of
authentication. Phase 5 must establish identity and authorization before any
governed tool execution.

The native development default uses the in-memory repository. Docker Compose
uses the Firestore emulator and performs transactional state/audit writes with
optimistic versions. Run `python scripts/tasks.py persistence-check` to prove
that state survives a Control API restart and `Last-Event-ID` resumes without
replaying the cursor event.
