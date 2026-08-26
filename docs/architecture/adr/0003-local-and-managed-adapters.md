# ADR 0003: Local and Google Cloud implementations share typed ports

- Status: Accepted
- Date: 2026-08-25

## Context

The golden path must run locally and in CI without credentials, while the
submission must visibly use Google Cloud managed services. Tests must remain
deterministic during cloud or model outages.

## Decision

Define typed application ports before infrastructure adapters. Use local
implementations for development and deterministic tests, then add Firestore,
Pub/Sub, Cloud Workflows, Cloud Tasks, Cloud Storage, Agent Platform, Memory
Bank, Model Armor, and Secret Manager adapters in their assigned phases.

The active adapter is selected by validated configuration. Local adapters may
model delivery and failure semantics, but they must not claim to be managed
services or silently fall back in a deployed sandbox.

## Consequences

- Local development stays fast and credential-free.
- Managed APIs can be version-verified immediately before implementation.
- Deployed readiness checks can fail clearly when a required adapter is absent.
- Contract tests must run against both local and managed implementations.
