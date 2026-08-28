"""Canonical JSON and SHA-256 helpers used for plan-bound decisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from changeops_contracts.models import ChangeEvent, RemediationPlan


def canonical_json(document: BaseModel | dict[str, Any]) -> str:
    """Serialize a contract or mapping using the project's canonical JSON profile.

    The profile uses UTF-8 JSON, recursively sorted object keys, compact
    separators, explicit nulls, and rejects non-finite numbers. Domain
    contracts restrict map keys to strings, so the representation is stable
    across supported Python and TypeScript implementations.
    """

    payload = document.model_dump(mode="json") if isinstance(document, BaseModel) else document
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_digest(document: BaseModel | dict[str, Any]) -> str:
    """Return a namespaced SHA-256 digest for a canonical JSON document."""

    encoded = canonical_json(document).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def calculate_plan_hash(plan: RemediationPlan) -> str:
    """Bind an approval or tool intent to the exact remediation plan document."""

    return sha256_digest(plan)


def derive_change_id(event: ChangeEvent) -> str:
    """Return the stable change identifier for an at-least-once source event."""

    digest = sha256_digest(
        {
            "event_id": event.event_id,
            "source": event.source.type,
            "tenant_id": event.tenant_id,
        }
    )
    return f"chg_{digest.removeprefix('sha256:')[:24]}"


def derive_workflow_id(event: ChangeEvent) -> str:
    """Return the stable workflow identifier for an at-least-once source event."""

    digest = sha256_digest(
        {
            "correlation_id": event.correlation_id,
            "event_id": event.event_id,
            "tenant_id": event.tenant_id,
        }
    )
    return f"wf_{digest.removeprefix('sha256:')[:24]}"
