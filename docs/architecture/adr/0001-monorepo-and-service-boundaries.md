# ADR 0001: Monorepo and independently deployable service boundaries

- Status: Accepted
- Date: 2026-08-25

## Context

Enterprise ChangeOps requires shared typed contracts while preserving distinct
runtime identities and scaling boundaries for the control plane, agent runtime,
gateway, tool services, sandbox systems, and verification runner.

## Decision

Use one repository with uv and npm workspaces. Keep each deployable service in
its own directory and container definition. Shared packages may contain
contracts or deterministic utilities, but services do not import another
service's implementation modules.

Only services that implement a real vertical slice are started. Future service
directories document ownership and responsibilities; they are not exposed as
working endpoints until implemented and tested.

## Consequences

- Contract changes can be reviewed atomically across Python and TypeScript.
- Cloud Run services can receive distinct identities and scaling policies.
- The repository requires explicit dependency direction and CI for both stacks.
- Local Compose may run services together without collapsing their boundaries.
