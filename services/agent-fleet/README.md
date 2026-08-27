# Agent Fleet

Phase 4 Google ADK runtime boundary. Exactly seven tenant-scoped agents return
typed, evidence-backed recommendations and never authorize or execute changes.

The default `AGENT_MODEL_MODE=fake` is deterministic and runs without cloud
credentials. For live Gemini on Vertex AI, set `AGENT_MODEL_MODE=live`,
`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, and
`GOOGLE_CLOUD_LOCATION`; the service fails closed if that configuration is
incomplete.

Endpoints:

- `GET /v1/agents` with `X-Tenant-ID`
- `GET /v1/agents/{agent_id}` with `X-Tenant-ID`
- `POST /v1/analyses` with `X-Tenant-ID`
- `GET /health/live`
