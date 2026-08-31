# ADR 0011: Managed governance is fail-closed behind typed local and cloud adapters

- Status: Accepted
- Date: 2026-08-29

## Context

Phase 8 requires prompt-injection defense, managed registry visibility, scoped
agent identity, cited tenant memory, Agent Gateway compatibility, and Secret
Manager. Local development must remain deterministic and credential-free, while
the submitted cloud deployment must not imply that a local simulation is a
managed Google Cloud decision.

The current Google Cloud interfaces were verified against official documentation
before implementation:

- Model Armor v1 uses the regional `sanitizeUserPrompt` method.
- Agent Registry exposes v1 agent-listing resources and registers custom agents
  through Service resources and A2A Agent Cards.
- Memory Bank retrieval is scoped to a Reasoning Engine and an exact scope map.
- Agent Gateway is a Network Services resource bound to an Agent Registry and a
  compatible region; it is infrastructure, not an in-process HTTP proxy.
- Agent Identity is Pre-GA and currently tied to Gemini Enterprise or Agent
  Runtime. Distinct least-privilege service accounts remain the scoped fallback.
- Secret Manager access returns base64 data with a CRC32C value that must be
  checked before use.

## Decision

Run every untrusted change summary through a `PromptGuard` before evidence,
model, or tool work. A block creates a redacted security audit event and a
`BLOCKED` change state. A missing or incomplete managed decision fails closed.

Use a local deterministic guard and disclosed synthetic incident-memory fixture
for tests. Mark historical memory as untrusted, tenant-scope every retrieval,
and require its evidence identifier to flow into agent output and the plan.

Provide verified managed adapters for Model Armor, Vertex AI Memory Bank, Agent
Registry visibility, and Secret Manager. Keep credentials in Application Default
Credentials or Secret Manager; never accept service-account keys in repository
configuration. Verify Secret Manager CRC32C before returning bytes.

Represent identities explicitly as local, Agent Identity, or distinct scoped
service accounts. Managed mode rejects local identities and incomplete resource
configuration at startup. Agent Gateway remains an optional managed deployment
resource because it cannot be emulated truthfully in-process.

## Consequences

- The required injection string is blocked before any tool request and is visible
  through the existing Control API audit and Control Tower security view.
- Local tests prove the governance contract but do not claim managed-service use.
- Live cloud completion still requires a project, region, APIs, IAM, Model Armor
  template, Agent Registry, Agent Engine Memory Bank, and optional Agent Gateway.
- Agent Identity availability must be rechecked in the target project; the
  service-account fallback stays distinct per agent and is documented rather
  than silently substituted.
