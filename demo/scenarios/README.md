# Demo scenarios

`python scripts/tasks.py sandbox-check` performs the Phase 2 golden scenario
against live HTTP services: reset, snapshot, forward migration, one controlled
Analytics failure, idempotent retry and replay, independent verification, and
reverse-order rollback to `customer_id`.

Later phases add event ingestion, approval, security, and durable-workflow
scenarios only when those behaviors are implemented.
