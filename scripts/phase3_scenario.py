"""Verify Firestore restart persistence and Last-Event-ID recovery over HTTP."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any

from control_api.demo import load_demo_seed

BASE_URL = os.environ.get("CONTROL_API_URL", "http://127.0.0.1:8000")
TENANT_ID = os.environ.get("PHASE3_TENANT_ID", "tenant_phase3_gate")
ACTOR_ID = "user_phase3_gate"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_document(document: dict[str, Any] | None, message: str) -> dict[str, Any]:
    if document is None:
        raise RuntimeError(message)
    return document


def request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    expected_status: int = 200,
    last_event_id: str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Actor-ID": ACTOR_ID,
        "X-Request-ID": "req_phase3_gate",
        "X-Tenant-ID": TENANT_ID,
    }
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    outgoing = urllib.request.Request(  # noqa: S310
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(outgoing, timeout=15) as response:  # noqa: S310
            status_code = response.status
            content_type = response.headers.get_content_type()
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status_code = error.code
        content_type = error.headers.get_content_type()
        body = error.read().decode("utf-8")
    require(
        status_code == expected_status,
        f"{method} {path} returned {status_code}, expected {expected_status}: {body}",
    )
    document = json.loads(body) if content_type == "application/json" else None
    return document, body


def seed() -> None:
    seed_contract = load_demo_seed()
    change = require_document(
        request(
            "POST",
            "/v1/demo/events/api-breaking-change",
            expected_status=201,
        )[0],
        "Demo seed did not return JSON.",
    )
    require(change["version"] == 1, "Seeded change did not start at version 1.")
    audit = require_document(
        request("GET", f"/v1/changes/{seed_contract.change_id}/audit")[0],
        "Initial audit response was not JSON.",
    )
    require(audit["count"] == 1, "Initial audit event is missing.")
    print(
        json.dumps(
            {
                "change_id": seed_contract.change_id,
                "initial_audit_event_id": audit["items"][0]["audit_event_id"],
                "status": "seeded",
                "tenant_id": TENANT_ID,
            },
            sort_keys=True,
        )
    )


def verify_after_restart() -> None:
    seed_contract = load_demo_seed()
    cursor = f"audit_{seed_contract.event_id}_received"
    persisted = require_document(
        request("GET", f"/v1/changes/{seed_contract.change_id}")[0],
        "Persisted change did not return JSON.",
    )
    require(persisted["version"] == 1, "Change state did not survive restart at version 1.")
    cancelled = require_document(
        request(
            "POST",
            f"/v1/changes/{seed_contract.change_id}/cancel",
            {"expected_version": 1, "trace_id": "trace_phase3_restart_gate"},
        )[0],
        "Cancellation did not return JSON.",
    )
    require(cancelled["status"] == "CANCELLED", "Persisted change could not be cancelled.")
    _, stream = request(
        "GET",
        f"/v1/changes/{seed_contract.change_id}/stream?follow=false",
        last_event_id=cursor,
    )
    require(stream.count("event: audit") == 1, "SSE replay did not return exactly one event.")
    require(cursor not in stream, "SSE replay repeated the cursor event.")
    require(
        "WORKFLOW_STATE_TRANSITION_SUCCEEDED" in stream,
        "SSE replay did not return the post-cursor transition.",
    )
    audit = require_document(
        request("GET", f"/v1/changes/{seed_contract.change_id}/audit")[0],
        "Audit response was not JSON.",
    )
    require(audit["count"] == 2, "Audit stream is incomplete.")
    print(
        json.dumps(
            {
                "change_id": seed_contract.change_id,
                "persisted_version_after_restart": persisted["version"],
                "sse_events_after_cursor": 1,
                "status": "passed",
                "tenant_id": TENANT_ID,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "verify-after-restart"))
    action = parser.parse_args().action
    if action == "seed":
        seed()
    else:
        verify_after_restart()


if __name__ == "__main__":
    main()
