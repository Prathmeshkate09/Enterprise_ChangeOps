# ADR 0004: Runtime and SDK version baseline

- Status: Accepted
- Date: 2026-08-25

## Context

The specification requires current API verification and prohibits invented SDK
methods. Google ADK 2.x introduced breaking changes to its agent API, event
model, session schema, and workflow runtime.

## Decision

Use Python 3.12, uv 0.11.x, Node.js 22, Next.js 16, React 19, and strict
TypeScript. ESLint remains on the supported 9.x line until the React lint
plugin included by Next.js supports ESLint 10. Commit Python and npm lockfiles.
The current Google ADK release is
2.7.1 and supports Python 3.12, but it is intentionally added only in Phase 4
after its exact workflow and structured-output APIs are verified. Use stable
model IDs `gemini-3.5-flash` and `gemini-3.5-flash-lite` when live model access
is implemented.

Do not use floating `latest` model aliases or install ADK development branches.

## Consequences

- The Phase 0 dependency graph stays small and auditable.
- ADK integration work must begin with a documentation and installed-version
  verification checkpoint.
- Lockfile updates require passing all existing gates.
