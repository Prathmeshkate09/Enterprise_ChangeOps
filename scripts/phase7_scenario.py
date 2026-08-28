"""Live server-rendered Control Tower and governed workflow Phase 7 gate."""

from __future__ import annotations

import html
import os
import urllib.parse
import urllib.request
from uuid import uuid4

from phase6_scenario import (
    approve,
    build_event,
    publish,
    reset_tenant,
    wait_for_workflow,
)

CONTROL_TOWER_URL = os.environ.get("CONTROL_TOWER_URL", "http://127.0.0.1:3000").rstrip("/")


def render_dashboard(tenant_id: str, change_id: str) -> str:
    query = urllib.parse.urlencode({"tenant_id": tenant_id, "change_id": change_id})
    request = urllib.request.Request(  # noqa: S310 - fixed local acceptance endpoint.
        f"{CONTROL_TOWER_URL}/?{query}",
        headers={"X-Request-ID": f"req_phase7_{uuid4().hex}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        if response.status != 200:
            raise AssertionError(f"Control Tower returned HTTP {response.status}.")
        return str(html.unescape(response.read().decode("utf-8")))


def assert_visible(page: str, *expected: str) -> None:
    missing = [text for text in expected if text not in page]
    if missing:
        raise AssertionError(f"Control Tower did not render expected evidence: {missing}")


def main() -> None:
    run_id = os.environ.get("PHASE7_RUN_ID", uuid4().hex[:12])
    tenant_id = f"tenant_phase7_{run_id}"
    reset_tenant(tenant_id)

    event = build_event(
        tenant_id=tenant_id,
        event_id=f"evt_phase7_{run_id}",
        event_type="api.contract.changed",
    )
    accepted = publish(event)
    change_id = str(accepted["change_id"])
    waiting = wait_for_workflow(event, change_id, {"WAITING_APPROVAL"})

    waiting_page = render_dashboard(tenant_id, change_id)
    assert_visible(
        waiting_page,
        "Approval workspace",
        "Exact-plan authorization",
        str(waiting["approval_id"]),
        "7 registered agents",
        "Hard disabled",
        "Closed tool registry",
        "crm.update_field_mapping",
    )

    approve(waiting)
    completed = wait_for_workflow(event, change_id, {"COMPLETED"})
    assert {task["status"] for task in completed["tasks"]} == {"SUCCEEDED"}

    completed_page = render_dashboard(tenant_id, change_id)
    assert_visible(
        completed_page,
        "Completed",
        "Approved",
        "Step-1-crm",
        "Step-2-analytics",
        "Step-3-support",
        "Workflow Verification Succeeded",
        "Tool Execution Succeeded",
        "Production writes off",
    )
    print(
        "Phase 7 gate passed: the Control Tower rendered the durable workflow, exact-plan "
        "approval, bounded agent and tool registries, completed task evidence, and audit trail.",
        flush=True,
    )


if __name__ == "__main__":
    main()
