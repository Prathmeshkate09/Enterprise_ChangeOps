"""Phase 5 HTTP security and acceptance gates."""

from typing import Any

from conftest import approve_and_start, authorization, build_intent
from fastapi.testclient import TestClient


def test_missing_authentication_fails_closed(gateway_stack: dict[str, Any]) -> None:
    with TestClient(gateway_stack["app"]) as client:
        response = client.get("/v1/tools")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_unapproved_write_is_blocked_and_audited(gateway_stack: dict[str, Any]) -> None:
    approve_and_start(gateway_stack)
    intent = build_intent(gateway_stack["plan"])
    tokens = gateway_stack["tokens"]
    with TestClient(gateway_stack["app"]) as client:
        response = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(tokens["crm"]),
            json={"intent": intent.model_dump(mode="json")},
        )
        audit = client.get("/v1/audit", headers=authorization(tokens["auditor"])).json()

    assert response.status_code == 409
    assert response.json()["code"] == "APPROVAL_REQUIRED"
    assert gateway_stack["executor"].execution_count == 0
    assert any(item["event_type"] == "TOOL_POLICY_DENIED" for item in audit["items"])


def test_exact_plan_executes_once_and_duplicate_replays(gateway_stack: dict[str, Any]) -> None:
    approve_and_start(gateway_stack)
    intent = build_intent(gateway_stack["plan"])
    tokens = gateway_stack["tokens"]
    payload = {"intent": intent.model_dump(mode="json"), "approval_id": "approval_phase5"}
    with TestClient(gateway_stack["app"]) as client:
        first = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(tokens["crm"]),
            json=payload,
        )
        duplicate_intent = build_intent(gateway_stack["plan"], intent_id="intent_duplicate")
        second = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(tokens["crm"]),
            json={
                "intent": duplicate_intent.model_dump(mode="json"),
                "approval_id": "approval_phase5",
            },
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert first.json()["execution_id"] == second.json()["execution_id"]
    assert gateway_stack["executor"].execution_count == 1
    configuration = gateway_stack["sandbox_store"].get("tenant_phase5")
    assert configuration.source_field == "customer_uuid"
    assert configuration.schema_version == 5


def test_old_plan_hash_and_cross_tenant_identity_fail_closed(
    gateway_stack: dict[str, Any],
) -> None:
    approve_and_start(gateway_stack)
    intent = build_intent(gateway_stack["plan"])
    old_document = intent.model_dump(mode="json")
    old_document["plan_hash"] = f"sha256:{'0' * 64}"
    tokens = gateway_stack["tokens"]
    with TestClient(gateway_stack["app"]) as client:
        old_plan = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(tokens["crm"]),
            json={"intent": old_document, "approval_id": "approval_phase5"},
        )
        cross_tenant = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(tokens["other_tenant"]),
            json={
                "intent": intent.model_dump(mode="json"),
                "approval_id": "approval_phase5",
            },
        )

    assert old_plan.status_code == 409
    assert old_plan.json()["code"] == "APPROVAL_REQUIRED"
    assert cross_tenant.status_code == 403
    assert gateway_stack["executor"].execution_count == 0


def test_tool_argument_injection_fails_registered_schema(gateway_stack: dict[str, Any]) -> None:
    approve_and_start(gateway_stack)
    intent = build_intent(gateway_stack["plan"]).model_dump(mode="json")
    intent["arguments"] = {
        "old_field": "customer_id",
        "new_field": "customer_uuid",
        "url": "https://attacker.invalid",
    }
    with TestClient(gateway_stack["app"]) as client:
        response = client.post(
            "/internal/v1/tool-intents/evaluate-and-execute",
            headers=authorization(gateway_stack["tokens"]["crm"]),
            json={"intent": intent, "approval_id": "approval_phase5"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"
    assert gateway_stack["executor"].execution_count == 0
