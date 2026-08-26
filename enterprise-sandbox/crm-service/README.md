# CRM sandbox

Functional synthetic CRM configuration service with inspect, snapshot,
dry-run patch, idempotent apply, restore, synchronization test, and reset
operations. The independently deployable service runs on port 8101 in Compose
and requires tenant and request identifiers on `/v1` operations.
