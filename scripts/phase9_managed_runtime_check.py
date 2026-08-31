"""Verify the private Phase 9 Cloud Run topology and authenticated health endpoints."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = "enterprise-changeops"
REGION = "us-central1"
PROJECT_NUMBER = "509035019856"
VERIFICATION_ACCOUNT = f"changeops-verification@{PROJECT}.iam.gserviceaccount.com"

SERVICES = {
    "changeops-control-tower": ("changeops-control-tower", "/api/health"),
    "changeops-control-api": ("changeops-control-api", "/health/ready"),
    "changeops-agent-fleet": ("changeops-orchestrator", "/health/live"),
    "changeops-event-gateway": ("changeops-event-gateway", "/health/ready"),
    "changeops-tool-gateway": ("changeops-tool-gateway", "/health/ready"),
    "changeops-workflow-coordinator": ("changeops-workflow", "/health/ready"),
    "changeops-catalog-sandbox": ("changeops-catalog-sandbox", "/health/ready"),
    "changeops-crm-sandbox": ("changeops-crm-sandbox", "/health/ready"),
    "changeops-analytics-sandbox": ("changeops-analytics-sandbox", "/health/ready"),
    "changeops-support-sandbox": ("changeops-support-sandbox", "/health/ready"),
}
IDENTITY_CALLERS = {
    "changeops-control-tower",
    "changeops-agent-fleet",
    "changeops-tool-gateway",
    "changeops-workflow-coordinator",
}
FIRESTORE_SERVICES = {
    "changeops-control-api",
    "changeops-event-gateway",
    "changeops-tool-gateway",
    "changeops-workflow-coordinator",
}


def gcloud(*arguments: str) -> str:
    executable = shutil.which("gcloud")
    if executable is None:
        raise RuntimeError("gcloud CLI is required for the managed-runtime check.")
    completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(3):
        completed = subprocess.run(  # noqa: S603
            [executable, "--quiet", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
        if attempt < 2:
            time.sleep(2)
    assert completed is not None
    detail = completed.stderr.strip() or "no error detail returned"
    raise RuntimeError(f"gcloud {' '.join(arguments[:3])} failed: {detail}")


def service_description(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            gcloud(
                "run",
                "services",
                "describe",
                name,
                "--project",
                PROJECT,
                "--region",
                REGION,
                "--format=json",
            )
        ),
    )


def assert_private(name: str) -> None:
    policy = json.loads(
        gcloud(
            "run",
            "services",
            "get-iam-policy",
            name,
            "--project",
            PROJECT,
            "--region",
            REGION,
            "--format=json",
        )
        or "{}"
    )
    members = {
        member for binding in policy.get("bindings", []) for member in binding.get("members", [])
    }
    if "allUsers" in members or "allAuthenticatedUsers" in members:
        raise AssertionError(f"{name} allows a public or project-unbounded principal.")


def environment(container: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in container.get("env", []) if "value" in item}


def assert_runtime(name: str, description: dict[str, Any], account_name: str) -> str:
    conditions = description.get("status", {}).get("conditions", [])
    ready = next((item for item in conditions if item.get("type") == "Ready"), None)
    if ready is None or ready.get("status") != "True":
        raise AssertionError(f"{name} is not Ready: {ready}")
    url = description.get("status", {}).get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise AssertionError(f"{name} has no canonical HTTPS URL.")

    template = description["spec"]["template"]
    expected_account = f"{account_name}@{PROJECT}.iam.gserviceaccount.com"
    actual_account = template["spec"].get("serviceAccountName")
    if actual_account != expected_account:
        raise AssertionError(f"{name} uses {actual_account}, expected {expected_account}.")
    env = environment(template["spec"]["containers"][0])
    if env.get("PRODUCTION_WRITES_ENABLED") != "false":
        raise AssertionError(f"{name} does not fail closed for production writes.")
    if name in IDENTITY_CALLERS and env.get("SERVICE_AUTH_MODE") != "google_cloud":
        raise AssertionError(f"{name} does not use managed service authentication.")
    if name in FIRESTORE_SERVICES and env.get("PERSISTENCE_BACKEND") != "firestore":
        raise AssertionError(f"{name} does not use Firestore persistence.")

    annotations = template.get("metadata", {}).get("annotations", {})
    service_annotations = description.get("metadata", {}).get("annotations", {})
    if name == "changeops-workflow-coordinator":
        if service_annotations.get("run.googleapis.com/minScale") != "1":
            raise AssertionError("Workflow Coordinator must keep one pull subscriber running.")
        if service_annotations.get("run.googleapis.com/maxScale") != "1":
            raise AssertionError("Workflow Coordinator must have exactly one pull subscriber.")
        if annotations.get("run.googleapis.com/cpu-throttling") != "false":
            raise AssertionError("Workflow Coordinator CPU must remain allocated between requests.")
    if name.endswith("-sandbox"):
        if service_annotations.get("run.googleapis.com/minScale") != "1":
            raise AssertionError(f"{name} must retain one synthetic-state instance.")
        if service_annotations.get("run.googleapis.com/maxScale") != "1":
            raise AssertionError(f"{name} must not split synthetic state across instances.")
    return url


def identity_token(audience: str) -> str:
    return gcloud(
        "auth",
        "print-identity-token",
        f"--impersonate-service-account={VERIFICATION_ACCOUNT}",
        f"--audiences={audience}",
        "--include-email",
    )


def assert_health(name: str, base_url: str, path: str) -> None:
    token = identity_token(base_url)
    request = Request(  # noqa: S310
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                if response.status != 200:
                    raise AssertionError(f"{name} health returned HTTP {response.status}.")
                response.read()
                return
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < 5:
                time.sleep(5)
    raise AssertionError(f"{name} authenticated health check failed: {last_error}")


def verify(service_names: Sequence[str] = tuple(SERVICES)) -> None:
    results: list[dict[str, str]] = []
    for name in service_names:
        account_name, health_path = SERVICES[name]
        description = service_description(name)
        assert_private(name)
        url = assert_runtime(name, description, account_name)
        assert_health(name, url, health_path)
        results.append({"name": name, "status": "ready-private", "url": url})
        print(f"verified {name}: ready-private", flush=True)
    print(json.dumps({"services": results, "verified_count": len(results)}, sort_keys=True))


if __name__ == "__main__":
    selected = tuple(sys.argv[1:]) or tuple(SERVICES)
    unknown = tuple(name for name in selected if name not in SERVICES)
    if unknown:
        raise SystemExit("Unknown services: " + ", ".join(unknown))
    verify(selected)
