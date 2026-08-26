"""Control API behavior, tenant isolation, and resumable SSE tests."""

from changeops_core import Settings
from changeops_persistence import InMemoryChangeStateRepository
from control_api.app import create_app
from control_api.demo import build_demo_change
from fastapi.testclient import TestClient

TENANT_HEADERS = {
    "X-Tenant-ID": "tenant_alpha",
    "X-Request-ID": "req_phase3_test",
}
MUTATION_HEADERS = {**TENANT_HEADERS, "X-Actor-ID": "user_change_manager_001"}


def make_client() -> TestClient:
    settings = Settings(APP_ENV="test", PERSISTENCE_BACKEND="memory", _env_file=None)
    return TestClient(
        create_app(
            repository=InMemoryChangeStateRepository(),
            settings=settings,
        )
    )


def seed_change(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/demo/events/api-breaking-change",
        headers=TENANT_HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def test_demo_change_is_idempotent_and_tenant_scoped() -> None:
    with make_client() as client:
        seeded = seed_change(client)
        replay = client.post(
            "/v1/demo/events/api-breaking-change",
            headers=TENANT_HEADERS,
        )
        cross_tenant = client.get(
            f"/v1/changes/{seeded['change_id']}",
            headers={"X-Tenant-ID": "tenant_beta"},
        )
        beta_list = client.get("/v1/changes", headers={"X-Tenant-ID": "tenant_beta"})

    assert replay.status_code == 200
    assert replay.json()["version"] == 1
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["error"]["code"] == "change_not_found"
    assert beta_list.json() == {"items": [], "count": 0}


def test_demo_change_rejects_identifier_collision() -> None:
    repository = InMemoryChangeStateRepository()
    settings = Settings(APP_ENV="test", PERSISTENCE_BACKEND="memory", _env_file=None)
    change, audit = build_demo_change("tenant_alpha")
    repository.add_with_audit(
        change.model_copy(update={"event_id": "evt_different_source_event"}),
        audit,
    )

    with TestClient(create_app(repository=repository, settings=settings)) as client:
        response = client.post(
            "/v1/demo/events/api-breaking-change",
            headers=TENANT_HEADERS,
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "change_already_exists"


def test_cancel_is_audited_and_sse_resumes_strictly_after_cursor() -> None:
    with make_client() as client:
        seeded = seed_change(client)
        initial_audit = client.get(
            f"/v1/changes/{seeded['change_id']}/audit",
            headers=TENANT_HEADERS,
        ).json()["items"]
        cursor = initial_audit[0]["audit_event_id"]

        cancelled = client.post(
            f"/v1/changes/{seeded['change_id']}/cancel",
            headers=MUTATION_HEADERS,
            json={"expected_version": 1, "trace_id": "trace_cancel_001"},
        )
        stream = client.get(
            f"/v1/changes/{seeded['change_id']}/stream?follow=false",
            headers={**TENANT_HEADERS, "Last-Event-ID": cursor},
        )
        tenant_audit = client.get("/v1/audit", headers=TENANT_HEADERS)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["version"] == 2
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.text.count("event: audit") == 1
    assert "WORKFLOW_STATE_TRANSITION_SUCCEEDED" in stream.text
    assert cursor not in stream.text
    assert tenant_audit.status_code == 200
    assert tenant_audit.json()["count"] == 2


def test_invalid_retry_is_rejected_and_audited() -> None:
    with make_client() as client:
        seeded = seed_change(client)
        retry = client.post(
            f"/v1/changes/{seeded['change_id']}/retry",
            headers=MUTATION_HEADERS,
            json={"expected_version": 1, "trace_id": "trace_retry_001"},
        )
        audit = client.get(
            f"/v1/changes/{seeded['change_id']}/audit",
            headers=TENANT_HEADERS,
        ).json()["items"]

    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "invalid_state_transition"
    rejected_events = [event for event in audit if event["status"] == "rejected"]
    assert len(rejected_events) == 1
    assert rejected_events[0]["event_type"] == "WORKFLOW_STATE_TRANSITION_REJECTED"


def test_errors_preserve_request_id_without_echoing_invalid_input() -> None:
    with make_client() as client:
        missing_tenant = client.get(
            "/v1/changes",
            headers={"X-Request-ID": "req_known"},
        )
        invalid_mutation = client.post(
            "/v1/changes/chg_phase3_001/cancel",
            headers=MUTATION_HEADERS,
            json={"expected_version": 0, "trace_id": "contains spaces"},
        )

    assert missing_tenant.status_code == 401
    assert missing_tenant.headers["X-Request-ID"] == "req_known"
    assert missing_tenant.json()["error"]["code"] == "tenant_required"
    assert invalid_mutation.status_code == 422
    assert all("input" not in detail for detail in invalid_mutation.json()["error"]["details"])


def test_unknown_sse_cursor_fails_before_stream_headers() -> None:
    with make_client() as client:
        seeded = seed_change(client)
        response = client.get(
            f"/v1/changes/{seeded['change_id']}/stream?follow=false",
            headers={**TENANT_HEADERS, "Last-Event-ID": "audit_unknown"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "audit_cursor_not_found"
