# Workflow Coordinator

Phase 6 boundary for deterministic workflow coordination, authenticated
approval callbacks, dependency-DAG execution, bounded retries, dead-letter
handling, independent verification, and snapshot compensation. Firestore holds
the authoritative workflow record while Pub/Sub supplies at-least-once event
delivery. Every mutating step continues to execute through the Tool Gateway.
