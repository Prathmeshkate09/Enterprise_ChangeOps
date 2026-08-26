# Customer API Registry sandbox

Functional synthetic contract registry and dependency graph for the
`customer_id` to `customer_uuid` golden path. The independently deployable
service runs on port 8100 in Compose and exposes tenant-scoped `/v1` catalog,
snapshot, activation, restore, verification, and reset operations.

Its disclosed seed includes API contract versions, compatibility metadata,
owners, change artifacts, and the unmanaged `order-service` dependency. The
service reports that dependency as a human-owned follow-up; it does not pretend
to automate an integration that is outside the sandbox.
