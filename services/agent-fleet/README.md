# Agent Fleet

Phase 4 Google ADK runtime boundary. Exactly seven tenant-scoped agents return
typed, evidence-backed recommendations and never authorize or execute changes.

The default `AGENT_MODEL_MODE=fake` and `GOVERNANCE_BACKEND=local` are
deterministic and run without cloud credentials. The local governance boundary
screens untrusted text before evidence retrieval or agent execution and uses a
tenant-scoped synthetic incident-memory fixture.

For managed governance, set `GOVERNANCE_BACKEND=google_cloud`, the Google Cloud
project/location, Model Armor template, Agent Registry location, Memory Bank
resource, and a non-local identity mode. Managed adapters use Application
Default Credentials and fail closed when configuration, authentication, or a
provider response is unavailable. `AGENT_IDENTITY_MODE=agent_identity` is the
preferred runtime identity mode; `service_account` is the explicit per-agent
fallback.

For live Gemini on Vertex AI, also set `AGENT_MODEL_MODE=live` and
`GOOGLE_GENAI_USE_VERTEXAI=true`.

Endpoints:

- `GET /v1/agents` with `X-Tenant-ID`
- `GET /v1/agents/{agent_id}` with `X-Tenant-ID`
- `POST /v1/analyses` with `X-Tenant-ID`
- `GET /health/live`
