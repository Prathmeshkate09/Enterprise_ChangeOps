# Enterprise ChangeOps

Enterprise ChangeOps is a governed, event-driven platform for discovering,
planning, approving, executing, and independently verifying cross-system
enterprise changes. The implementation follows the checked-in
phase-gated architecture and keeps deterministic application code in control
of workflow state, authorization, approvals, retries, and tool execution.

**Phases 0 through 9 are complete; Phase 9 deploys the full private managed sandbox.**
The repository includes runnable control
shells, versioned Python/TypeScript contracts, cross-runtime canonical plan
hashing, audited deterministic transitions, tenant boundaries, and four
independently deployable enterprise sandbox services. Firestore now holds
tenant-partitioned operational state and transactional audit evidence, while
the Control API exposes resumable change streams. The services use disclosed
synthetic state to execute, verify, and roll back the `customer_id` to
`customer_uuid` migration. Authenticated tool intents now pass through a
deterministic policy engine, exact-plan approval, transactional idempotency,
typed sandbox adapters, quotas, and audit enforcement; core results are not
hardcoded. Authenticated events now enter a transactional Firestore inbox,
publish through the Pub/Sub emulator, and drive a restart-safe workflow that
pauses for exact-plan approval, retries transient failures, executes the plan
DAG, verifies each system independently, rolls back from hashed snapshots, and
dead-letters permanent failures. The responsive Control Tower now renders measured
tenant state, durable workflows, the seven-agent fleet, exact-plan approvals,
closed tool registry, dead letters, and merged audit evidence. Its sandbox-only
server actions start the golden change and record approval decisions while live
SSE refreshes follow the execution to completion. Production writes remain
disabled. Phase 8 now screens untrusted change content before agent work, records
visible security blocks, adds tenant-scoped prior-incident memory as cited
untrusted evidence, exposes distinct identities and bounded registries, and
provides fail-closed Model Armor, Memory Bank, Agent Registry, and Secret Manager
adapters. The repository tests and acceptance commands below reproduce the
implemented behavior locally.

## Prerequisites

- Python 3.12 (the setup task installs a workspace-managed copy with `uv`)
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm 11
- Docker Desktop for the optional Compose path
- GNU Make, or use the documented Python task equivalents on Windows

Google Cloud CLI and credentials are not required for local development; the
Compose stack runs the official Firestore emulator image. Never commit
credentials or service-account keys.

## Local setup

Copy `.env.example` to `.env.local` only when overriding defaults. Do not put
credentials in tracked files.

```text
python scripts/tasks.py setup
python scripts/tasks.py lint
python scripts/tasks.py test
python scripts/tasks.py audit
python scripts/tasks.py build
python scripts/tasks.py smoke
# With all Compose services running:
python scripts/tasks.py sandbox-check
# Builds the emulator/API, restarts only the API, and verifies recovery:
python scripts/tasks.py persistence-check
# Builds the four sandboxes and seven-agent ADK fleet, then runs its golden event:
python scripts/tasks.py agent-fleet-check
# Builds Firestore, the Tool Gateway, and sandboxes, then proves the Phase 5 gates:
python scripts/tasks.py tool-gateway-check
# Builds the Phase 6 stack and proves restart, retry, DLQ, and rollback behavior:
python scripts/tasks.py workflow-check
# Builds the full UI stack and proves the Phase 7 operational view and workflow:
python scripts/tasks.py control-tower-check
# Proves the Phase 8 security block, registry visibility, and cited memory gate:
python scripts/tasks.py managed-governance-check
# Calls the real configured Google Cloud governance resources using ADC:
python scripts/tasks.py managed-cloud-check
# Verifies all ten private Cloud Run services and authenticated health endpoints:
python scripts/tasks.py managed-runtime-check
```

## Private managed sandbox

Phase 9 builds the ten runtime images with `deploy/cloudbuild-managed-runtime.yaml` and deploys
them with keyless service identities, Secret Manager, Firestore, and Pub/Sub:

```powershell
.\deploy\phase9-managed-runtime.ps1 `
  -Project enterprise-changeops `
  -Region us-central1 `
  -Tag phase9-20260831-03
python scripts/tasks.py managed-runtime-check
```

No service grants unauthenticated access. Open the managed Control Tower through your authenticated
Google Cloud session, leave the command running, and browse to `http://127.0.0.1:3000`:

```powershell
gcloud run services proxy changeops-control-tower `
  --project enterprise-changeops `
  --region us-central1 `
  --port 3000
```

The managed sandbox keeps one Event Gateway, one Workflow Coordinator, and one instance of each
synthetic enterprise service running. Those six instances incur ongoing cost. Synthetic enterprise state can reset
when a revision restarts; durable control, workflow, idempotency, and audit state remains in
Firestore. Production writes remain disabled.

Start both development services until interrupted:

```text
python scripts/tasks.py dev
```

Endpoints:

- Control Tower: `http://127.0.0.1:3000`
- Control Tower health: `http://127.0.0.1:3000/api/health`
- Control API: `http://127.0.0.1:8000`
- Control API docs: `http://127.0.0.1:8000/docs`
- API liveness/readiness: `/health/live` and `/health/ready`
- Tenant changes: `/v1/changes` and `/v1/changes/{change_id}`
- Change audit/SSE: `/v1/changes/{change_id}/audit` and
  `/v1/changes/{change_id}/stream`
- Tenant audit: `/v1/audit`
- Local Firestore emulator: `127.0.0.1:8085`
- Customer API Registry: `http://127.0.0.1:8100`
- CRM sandbox: `http://127.0.0.1:8101`
- Analytics sandbox: `http://127.0.0.1:8102`
- Support sandbox: `http://127.0.0.1:8103`
- Agent Fleet and OpenAPI docs: `http://127.0.0.1:8200` and `http://127.0.0.1:8200/docs`
- Tool Gateway and OpenAPI docs: `http://127.0.0.1:8300` and `http://127.0.0.1:8300/docs`
- Event Gateway and OpenAPI docs: `http://127.0.0.1:8400` and `http://127.0.0.1:8400/docs`
- Workflow Coordinator and OpenAPI docs: `http://127.0.0.1:8500` and `http://127.0.0.1:8500/docs`
- Local Pub/Sub emulator: `127.0.0.1:8086`

On systems with GNU Make, the corresponding gates are `make setup`,
`make lint`, `make test`, `make audit`, `make build`, `make smoke`, and
`make dev`.

## Docker Compose

With Docker Desktop running, start the complete local application:

```powershell
docker compose up -d --build --wait
```

Open the operational Control Tower:

```text
http://127.0.0.1:3000
```

Compose uses disclosed local-only signing defaults unless environment overrides
are supplied. Never reuse those defaults outside the sandbox. It starts the
Firestore and Pub/Sub emulators, Control API, Control Tower, Event Gateway,
Workflow Coordinator, Tool Gateway, Agent Fleet, and all four functional
enterprise sandbox services. In a second terminal, run the live
acceptance gates:

```text
python scripts/tasks.py sandbox-check
python scripts/tasks.py persistence-check
python scripts/tasks.py agent-fleet-check
python scripts/tasks.py tool-gateway-check
python scripts/tasks.py workflow-check
python scripts/tasks.py control-tower-check
python scripts/tasks.py managed-governance-check
python scripts/tasks.py managed-cloud-check
```

The scenario resets its tenant, snapshots every service, migrates and verifies
the field, exercises one idempotently retried Analytics failure, and restores
all four snapshots in reverse order.

The persistence scenario creates a fresh tenant, seeds a change, restarts only
the Control API container, reads the same Firestore-backed version, performs a
transition, and resumes SSE strictly after the pre-restart event ID.

The Control Tower scenario creates a fresh tenant and durable workflow, checks
the server-rendered approval and security evidence, approves the exact plan,
waits for completion, and confirms the completed tasks and audit evidence are
rendered without relying on backend logs.

The managed-governance scenario submits the required prompt-injection attack,
confirms a visible block before any tool task, verifies all seven scoped agents
and bounded tools are registered, and proves prior incident memory influences
analysis through an evidence reference. This is the local adapter gate; it does
not claim that Google Cloud managed resources were called. The separate
`managed-cloud-check` requires `GOVERNANCE_BACKEND=google_cloud`, the documented
Google Cloud resource settings, a non-local identity mode, `DEMO_TENANT_ID`
scoped to a synthetic Memory Bank record, and Application Default Credentials.
It calls Model Armor, Agent Registry, and Memory Bank and fails if the attack is
not blocked, tenant isolation fails, or the seven identity references are not
distinct.

## Repository layout

```text
apps/control-tower/             Next.js operational UI
services/control-api/           Tenant-facing FastAPI control API
services/agent-fleet/           Seven-agent Google ADK analysis fleet
services/tool-gateway/          Authenticated approval and typed execution boundary
services/event-gateway/         Authenticated transactional event ingestion
services/workflow-coordinator/  Durable callback, DAG, retry, verification and rollback
tool-services/                  Governed typed tool adapters
enterprise-sandbox/             Four functional synthetic enterprise systems
packages/changeops-core/        Shared validated config and structured logging
packages/contracts-python/      Immutable Pydantic wire contracts and plan hashing
packages/contracts-typescript/  Strict shared TypeScript wire contracts
packages/persistence/           Tenant-scoped memory and Firestore adapters
packages/policy-engine/         Deterministic RBAC, ABAC, risk and approval policy
packages/                       Contracts, persistence, observability and test packages
infrastructure/                 Terraform, Workflows and Cloud Build assets
evaluations/                    Agent datasets, scorers and measured reports
tests/                          Cross-service contract, integration, security and E2E tests
docs/                           Plan, architecture decisions and operating documentation
```

## Security baseline

- `PRODUCTION_WRITES_ENABLED=true` is rejected at configuration load time.
- Logs recursively redact credentials, authorization values, tokens, secrets,
  email addresses, and common API-key fields.
- Cloud configuration is optional locally and must arrive through environment
  variables or Secret Manager in managed mode.
- Managed governance rejects missing Model Armor, Agent Registry, Memory Bank,
  location, project, or scoped identity configuration at startup.
- Historical memory is untrusted input and must remain tenant scoped and cited.
- The Control Tower always labels the environment as `SANDBOX`.

See [ADR 0002](docs/architecture/adr/0002-deterministic-control-plane.md)
for the permanent control boundary.
