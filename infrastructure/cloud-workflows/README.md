# Cloud Workflows

Phase 6 implements and verifies the durable workflow contract locally with the
Firestore and Pub/Sub emulators. The callback payload accepted by the
coordinator is:

```json
{
  "tenant_id": "tenant-id",
  "change_id": "change-id",
  "approval_id": "approval-id",
  "plan_hash": "sha256:...",
  "plan_version": 1,
  "status": "APPROVED",
  "decided_at": "2026-08-28T12:00:00Z"
}
```

A managed Cloud Workflows definition is intentionally not presented as
deployable yet. Its callback endpoint is execution-specific and requires a
managed caller with `workflows.callbacks.send`; binding that workload identity,
Secret Manager material, Cloud Run audience, and regional deployment belongs
to the managed governance/deployment phases. The local workflow does not
silently impersonate that managed IAM path.

See ADR 0009 and `services/workflow-coordinator` for the verified runtime
semantics that the managed adapter must preserve.
