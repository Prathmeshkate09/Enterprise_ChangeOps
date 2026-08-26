# Analytics sandbox

Functional synthetic ETL configuration service with field-usage search,
snapshot, dry-run patch, idempotent apply, restore, data-quality verification,
and reset operations. The independently deployable service runs on port 8102
in Compose. A controlled endpoint injects exactly one transient failure so the
demo can prove retry safety without creating a duplicate mutation.
