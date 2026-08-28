# Event Gateway

Phase 6 deployable boundary for authenticated event ingestion and Pub/Sub
publication. `POST /v1/events/change` verifies an HMAC signature over the exact
request bytes, enforces the strict `ChangeEvent` contract and request limits,
stores an idempotent tenant-scoped inbox record, and returns `202` only after
the normalized event has been published. Identical delivery is replay-safe;
conflicting reuse and publication failure fail explicitly.
