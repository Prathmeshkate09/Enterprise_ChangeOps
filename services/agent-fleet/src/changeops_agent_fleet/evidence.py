"""Read-only, tenant-scoped evidence acquisition for the agent fleet."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Protocol

import httpx
from changeops_contracts import ChangeEvent, EvidenceItem, EvidenceTrust, sha256_digest


class EvidenceUnavailableError(RuntimeError):
    """Raised when authoritative sandbox evidence cannot be obtained."""


class EvidenceProvider(Protocol):
    async def collect(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]: ...


class HttpEvidenceProvider:
    """Fetch evidence only from configured service origins and fixed GET routes."""

    def __init__(
        self,
        service_urls: Mapping[str, str],
        *,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._service_urls = {name: url.rstrip("/") for name, url in service_urls.items()}
        self._timeout = timeout_seconds
        self._client = client

    async def collect(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]:
        headers = {"X-Tenant-ID": event.tenant_id}
        old_field = _field_from_event(event, old=True)
        requests = (
            ("catalog-contract", "catalog", "/v1/contracts/customer-api", None),
            ("catalog-dependencies", "catalog", "/v1/dependencies", None),
            ("crm-configuration", "crm", "/v1/configuration", None),
            ("analytics-configuration", "analytics", "/v1/configuration", None),
            ("analytics-field-usage", "analytics", "/v1/field-usage", {"field": old_field}),
            ("support-configuration", "support", "/v1/configuration", None),
            ("support-field-usage", "support", "/v1/field-usage", {"field": old_field}),
        )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            responses = await asyncio.gather(
                *(
                    client.get(
                        f"{self._service_urls[service]}{path}",
                        headers=headers,
                        params=params,
                    )
                    for _, service, path, params in requests
                )
            )
            observed_at = datetime.now(UTC)
            evidence: list[EvidenceItem] = []
            for request_spec, response in zip(requests, responses, strict=True):
                evidence_id, service, path, _ = request_spec
                response.raise_for_status()
                payload = response.json()
                evidence.append(
                    _evidence_item(
                        evidence_id=evidence_id,
                        tenant_id=event.tenant_id,
                        source_system=service,
                        source_resource=f"{service}://{path.lstrip('/')}",
                        payload=payload,
                        observed_at=observed_at,
                    )
                )
            evidence.append(policy_evidence(event.tenant_id, observed_at))
            return tuple(evidence)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise EvidenceUnavailableError("authoritative evidence collection failed") from error
        finally:
            if owns_client:
                await client.aclose()


class StaticEvidenceProvider:
    """Test provider that derives evidence from disclosed fixture payloads."""

    def __init__(self, payloads: Mapping[str, Mapping[str, Any]]) -> None:
        self._payloads = payloads

    async def collect(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]:
        observed_at = event.received_at
        items = tuple(
            _evidence_item(
                evidence_id=evidence_id,
                tenant_id=event.tenant_id,
                source_system=str(payload["source_system"]),
                source_resource=str(payload["source_resource"]),
                payload=dict(payload["attributes"]),
                observed_at=observed_at,
            )
            for evidence_id, payload in self._payloads.items()
        )
        return (*items, policy_evidence(event.tenant_id, observed_at))


def policy_evidence(tenant_id: str, observed_at: datetime) -> EvidenceItem:
    resource = files("changeops_agent_fleet.seed").joinpath("policies.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    payload = document["policies"][0]
    return _evidence_item(
        evidence_id="policy-sandbox-change",
        tenant_id=tenant_id,
        source_system="policy-catalog",
        source_resource="policy://versioned/POL-SANDBOX-BREAKING-CHANGE",
        payload=payload,
        observed_at=observed_at,
    )


def _field_from_event(event: ChangeEvent, *, old: bool) -> str:
    summary = event.change.summary
    separator = " to "
    if separator in summary:
        before, after = summary.rsplit(separator, maxsplit=1)
        value = before.split()[-1] if old else after.split()[0]
        return value.strip("`'\".,")
    return event.change.old_version if old else event.change.new_version


def field_transition(event: ChangeEvent) -> tuple[str, str]:
    return _field_from_event(event, old=True), _field_from_event(event, old=False)


def _evidence_item(
    *,
    evidence_id: str,
    tenant_id: str,
    source_system: str,
    source_resource: str,
    payload: Any,
    observed_at: datetime,
) -> EvidenceItem:
    attributes = payload if isinstance(payload, dict) else {"items": payload}
    return EvidenceItem(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        source_system=source_system,
        source_resource=source_resource,
        summary=f"Observed {evidence_id} from the tenant-scoped sandbox.",
        content_hash=sha256_digest(attributes),
        trust=EvidenceTrust.PLATFORM,
        observed_at=observed_at,
        attributes=attributes,
    )
