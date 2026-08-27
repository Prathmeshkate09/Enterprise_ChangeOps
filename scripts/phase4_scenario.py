"""Live Docker Compose acceptance gate for the Phase 4 agent fleet."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

BASE_URL = "http://127.0.0.1:8200"


def request_json(
    method: str,
    path: str,
    tenant_id: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "X-Tenant-ID": tenant_id},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-phase4-{suffix}"
    timestamp = datetime.now(UTC).isoformat()
    event = {
        "schema_version": "1.0",
        "event_id": f"evt-phase4-{suffix}",
        "tenant_id": tenant_id,
        "event_type": "api.contract.changed",
        "source": {
            "type": "github",
            "external_id": "pr-42",
            "url": "https://example.invalid/demo/pr/42",
        },
        "occurred_at": timestamp,
        "received_at": timestamp,
        "subject": {
            "system_id": "customer-api",
            "resource_type": "api-contract",
            "resource_id": "customer-api-v2",
        },
        "change": {
            "summary": "Rename customer_id to customer_uuid",
            "old_version": "1.4.0",
            "new_version": "2.0.0",
            "artifact_refs": ["artifact://contracts/customer-v2-diff.json"],
        },
        "correlation_id": f"correlation-{suffix}",
        "trace_id": f"trace-{suffix}",
    }
    registrations = request_json("GET", "/v1/agents", tenant_id)
    assert len(registrations) == 7
    assert all("*" not in tool for item in registrations for tool in item["allowed_tools"])
    result = request_json(
        "POST",
        "/v1/analyses",
        tenant_id,
        {"change_id": f"chg-phase4-{suffix}", "event": event},
    )
    assert len(result["remediation_proposals"]) == 3
    assert result["impact"]["evidence_refs"]
    assert all(proposal["evidence_refs"] for proposal in result["remediation_proposals"])
    assert len(result["invocations"]) == 7
    assert all(record["tool_calls"] == 0 for record in result["invocations"])
    assert result["max_parallel_agents"] >= 3
    print(
        "Phase 4 gate passed: seven bounded agents produced evidence-backed "
        "impact and three concurrent remediation proposals.",
        flush=True,
    )


if __name__ == "__main__":
    main()
