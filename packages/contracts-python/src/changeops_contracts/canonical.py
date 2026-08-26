"""Canonical JSON and SHA-256 helpers used for plan-bound decisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from changeops_contracts.models import RemediationPlan


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
