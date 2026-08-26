# ADR 0002: Deterministic control plane owns every consequential decision

- Status: Accepted
- Date: 2026-08-25

## Context

Model output may be useful for impact discovery and remediation proposals, but
it is probabilistic and may contain prompt-injected or malformed instructions.
Approval integrity and enterprise writes cannot depend on model judgment.

## Decision

Deterministic, typed application code exclusively owns state transitions, risk
classification, identity and scope checks, policy enforcement, approval
validation, idempotency, retries, execution ordering, and rollback activation.
Agents may produce evidence-backed recommendations only. Every tool request must
enter through the governed Tool Gateway, and missing security dependencies fail
closed.

Production writes are disabled as an invariant in the hackathon build, not as a
UI option.

## Consequences

- Agent output remains untrusted input to deterministic validation.
- Tests can prove safety properties without invoking a live model.
- The gateway becomes a high-value, intentionally narrow security boundary.
- Model changes cannot silently alter authorization behavior.
