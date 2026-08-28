"""Phase 6 authenticated inbox and publication acceptance tests."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from changeops_contracts import (
    ChangeDetails,
    ChangeEvent,
    ChangeSource,
    ChangeSubject,
)
from changeops_core import AppEnvironment, Settings
from changeops_event_gateway.app import create_app
from changeops_event_gateway.repository import InMemoryEventInboxRepository
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
TEST_KEY_MATERIAL = "phase6-event-webhook-test-secret-material"


class RecordingPublisher:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.publish_count = 0

    def ensure_ready(self) -> None:
        return None

    def check_ready(self) -> None:
        return None

    def publish(self, event: ChangeEvent, change_id: str) -> str:
        del event, change_id
        self.publish_count += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("injected publisher failure")
        return f"message-{self.publish_count}"


def build_event(*, summary: str = "Rename customer_id to customer_uuid") -> ChangeEvent:
    return ChangeEvent(
        schema_version="1.0",
        event_id="evt_phase6_gateway",
        tenant_id="tenant_phase6_gateway",
        event_type="api.contract.changed",
        source=ChangeSource(
            type="github",
            external_id="pr-42",
            url="https://example.invalid/pr/42",
        ),
        occurred_at=NOW,
        received_at=NOW,
        subject=ChangeSubject(
            system_id="customer-api",
            resource_type="api-contract",
            resource_id="customer-v2",
        ),
        change=ChangeDetails(
            summary=summary,
            old_version="1.4.0",
            new_version="2.0.0",
            artifact_refs=("artifact://contracts/customer-v2-diff.json",),
        ),
        correlation_id="correlation-phase6",
        trace_id="trace-phase6",
    )


def signed_headers(body: bytes) -> dict[str, str]:
    signature = hmac.new(TEST_KEY_MATERIAL.encode(), body, hashlib.sha256).hexdigest()
    return {"X-ChangeOps-Signature": f"sha256={signature}"}


def build_app(publisher: RecordingPublisher) -> TestClient:
    app = create_app(
        settings=Settings(
            app_env=AppEnvironment.TEST,
            event_gateway_webhook_secret=TEST_KEY_MATERIAL,
        ),
        repository=InMemoryEventInboxRepository(),
        publisher=publisher,
        clock=lambda: NOW,
    )
    return TestClient(app)


def test_authenticated_duplicate_event_publishes_once() -> None:
    publisher = RecordingPublisher()
    event = build_event()
    body = event.model_dump_json().encode()

    with build_app(publisher) as client:
        first = client.post("/v1/events/change", content=body, headers=signed_headers(body))
        duplicate = client.post("/v1/events/change", content=body, headers=signed_headers(body))

    assert first.status_code == 202, first.text
    assert duplicate.status_code == 202, duplicate.text
    assert first.json()["change_id"] == duplicate.json()["change_id"]
    assert first.json()["replayed"] is False
    assert duplicate.json()["replayed"] is True
    assert publisher.publish_count == 1


def test_publish_failure_is_persisted_and_identical_retry_recovers() -> None:
    publisher = RecordingPublisher(failures=1)
    body = build_event().model_dump_json().encode()

    with build_app(publisher) as client:
        failed = client.post("/v1/events/change", content=body, headers=signed_headers(body))
        retried = client.post("/v1/events/change", content=body, headers=signed_headers(body))

    assert failed.status_code == 503
    assert failed.json()["code"] == "PUBSUB_PUBLISH_FAILED"
    assert retried.status_code == 202, retried.text
    assert retried.json()["replayed"] is True
    assert publisher.publish_count == 2


def test_invalid_signature_and_idempotency_collision_fail_closed() -> None:
    publisher = RecordingPublisher()
    event = build_event()
    body = event.model_dump_json().encode()
    changed_body = build_event(summary="A different payload").model_dump_json().encode()

    with build_app(publisher) as client:
        unauthorized = client.post("/v1/events/change", content=body)
        accepted = client.post("/v1/events/change", content=body, headers=signed_headers(body))
        collision = client.post(
            "/v1/events/change",
            content=changed_body,
            headers=signed_headers(changed_body),
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "INVALID_SIGNATURE"
    assert accepted.status_code == 202
    assert collision.status_code == 409
    assert collision.json()["code"] == "EVENT_IDEMPOTENCY_CONFLICT"
    assert publisher.publish_count == 1
