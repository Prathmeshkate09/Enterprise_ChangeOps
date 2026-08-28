# Enterprise ChangeOps

Enterprise ChangeOps is a governed, event-driven platform for discovering,
planning, approving, executing, and independently verifying cross-system
enterprise changes. The implementation follows the checked-in
phase-gated architecture and keeps deterministic application code in control
of workflow state, authorization, approvals, retries, and tool execution.

**Phases 0 through 5 are complete.** The repository includes runnable control
shells, versioned Python/TypeScript contracts, cross-runtime canonical plan
hashing, audited deterministic transitions, tenant boundaries, and four
independently deployable enterprise sandbox services. Firestore now holds
tenant-partitioned operational state and transactional audit evidence, while
the Control API exposes resumable change streams. The services use disclosed
synthetic state to execute, verify, and roll back the `customer_id` to
`customer_uuid` migration. Authenticated tool intents now pass through a
deterministic policy engine, exact-plan approval, transactional idempotency,
typed sandbox adapters, quotas, and audit enforcement; core results are not
hardcoded. Production writes remain disabled. The repository tests and
acceptance commands below reproduce the implemented behavior locally.

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
```

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

On systems with GNU Make, the corresponding gates are `make setup`,
`make lint`, `make test`, `make audit`, `make build`, `make smoke`, and
`make dev`.

## Docker Compose

With Docker Desktop running, generate a process-local signing key:

```powershell
$env:TOOL_GATEWAY_AUTH_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start Compose:

```text
docker compose up --build
```

Compose starts the Firestore emulator, Control API, Control Tower, and all four
functional enterprise sandbox services. In a second terminal, run both live
acceptance gates:

```text
python scripts/tasks.py sandbox-check
python scripts/tasks.py persistence-check
python scripts/tasks.py agent-fleet-check
python scripts/tasks.py tool-gateway-check
```

The scenario resets its tenant, snapshots every service, migrates and verifies
the field, exercises one idempotently retried Analytics failure, and restores
all four snapshots in reverse order.

The persistence scenario creates a fresh tenant, seeds a change, restarts only
the Control API container, reads the same Firestore-backed version, performs a
transition, and resumes SSE strictly after the pre-restart event ID.

## Repository layout

```text
apps/control-tower/             Next.js operational UI
services/control-api/           Tenant-facing FastAPI control API
services/agent-fleet/           Seven-agent Google ADK analysis fleet
services/tool-gateway/          Authenticated approval and typed execution boundary
services/                       Future independently deployable control services
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
  variables or Secret Manager later.
- The Control Tower always labels the environment as `SANDBOX`.

See [ADR 0002](docs/architecture/adr/0002-deterministic-control-plane.md)
for the permanent control boundary.
