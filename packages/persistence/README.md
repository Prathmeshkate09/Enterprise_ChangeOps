# Persistence

Tenant-scoped repository protocols with deterministic in-memory and durable
Firestore implementations. State updates and audit events are committed
atomically with optimistic concurrency. Firestore records use server
timestamps and live below tenant-owned paths; tenant audit listing uses a
transactionally maintained tenant index rather than a global collection scan.

The in-memory adapter is the default for native development and deterministic
tests. Set `PERSISTENCE_BACKEND=firestore` with `GOOGLE_CLOUD_PROJECT` and,
locally, `FIRESTORE_EMULATOR_HOST` to use Firestore. The Compose configuration
provides these values automatically.
