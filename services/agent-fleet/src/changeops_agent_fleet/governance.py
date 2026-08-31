"""Feature-flagged local and Google Cloud governance adapters."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Protocol

import google.auth
import google_crc32c
import httpx
from changeops_contracts import ChangeEvent, EvidenceItem, EvidenceTrust, sha256_digest
from changeops_core import GovernanceBackend, Settings
from google.auth.transport.requests import Request as GoogleAuthRequest
from pydantic import BaseModel, ConfigDict, JsonValue

_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_RESOURCE_ID = re.compile(r"^[a-zA-Z0-9._-]+$")
_MODEL_ARMOR_TEMPLATE = re.compile(
    r"^projects/(?P<project>[a-z][a-z0-9-]{4,28}[a-z0-9])/locations/"
    r"(?P<location>[a-z0-9-]+)/templates/(?P<template>[a-zA-Z0-9_-]+)$"
)
_MEMORY_BANK = re.compile(
    r"^projects/(?P<project>(?:[a-z][a-z0-9-]{4,28}[a-z0-9]|[0-9]{6,20}))/locations/"
    r"(?P<location>[a-z0-9-]+)/reasoningEngines/(?P<engine>[0-9]+)$"
)


class GovernanceUnavailableError(RuntimeError):
    """Raised when an enabled governance dependency cannot make a decision."""


class PromptScreeningResult(BaseModel):
    """Redacted, auditable prompt-screening outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    blocked: bool
    categories: tuple[str, ...]
    input_hash: str
    invocation_result: str
    template_reference: str


class PromptBlockedError(RuntimeError):
    """Raised before evidence, model, or tool work when screening rejects input."""

    def __init__(self, result: PromptScreeningResult) -> None:
        super().__init__("PROMPT_INJECTION_BLOCKED")
        self.result = result


class PromptGuard(Protocol):
    async def screen(self, text: str) -> PromptScreeningResult: ...


class MemoryRetriever(Protocol):
    async def retrieve(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]: ...


class AccessTokenProvider(Protocol):
    async def token(self) -> str: ...


class IdentityResolver(Protocol):
    def reference(self, tenant_id: str, agent_id: str) -> str: ...


class GoogleAuthTokenProvider:
    """Application Default Credentials token provider with no key-file support."""

    def __init__(self) -> None:
        credentials, _ = google.auth.default(scopes=(_CLOUD_SCOPE,))
        self._credentials: Any = credentials

    async def token(self) -> str:
        if not self._credentials.valid or not self._credentials.token:
            await asyncio.to_thread(self._credentials.refresh, GoogleAuthRequest())
        token = self._credentials.token
        if not isinstance(token, str) or not token:
            raise GovernanceUnavailableError("Application Default Credentials returned no token.")
        return token


class DeterministicPromptGuard:
    """Disclosed local guard that deterministically models the managed security gate."""

    _RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("instruction_override", ("ignore prior", "ignore previous", "ignore all policies")),
        ("data_exfiltration", ("export all customer data", "send customer data externally")),
        ("secret_exfiltration", ("reveal credentials", "export credentials", "reveal secrets")),
        ("system_prompt_exfiltration", ("reveal system prompt", "show system prompt")),
        ("guardrail_bypass", ("disable guardrails", "bypass security screening")),
    )

    async def screen(self, text: str) -> PromptScreeningResult:
        normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
        categories = tuple(
            category
            for category, indicators in self._RULES
            if any(indicator in normalized for indicator in indicators)
        )
        return PromptScreeningResult(
            provider="deterministic-local",
            blocked=bool(categories),
            categories=categories,
            input_hash=sha256_digest({"text": text}),
            invocation_result="SUCCESS",
            template_reference="local://governance/prompt-injection-v1",
        )


class ModelArmorPromptGuard:
    """Regional Model Armor sanitizeUserPrompt REST adapter."""

    def __init__(
        self,
        *,
        template: str,
        token_provider: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        match = _MODEL_ARMOR_TEMPLATE.fullmatch(template)
        if match is None:
            raise ValueError("MODEL_ARMOR_TEMPLATE must be a full template resource name.")
        self._template = template
        self._location = match.group("location")
        self._token_provider = token_provider
        self._client = client
        self._timeout = timeout_seconds

    async def screen(self, text: str) -> PromptScreeningResult:
        endpoint = (
            f"https://modelarmor.{self._location}.rep.googleapis.com/v1/"
            f"{self._template}:sanitizeUserPrompt"
        )
        payload = await _authorized_json(
            method="POST",
            url=endpoint,
            token_provider=self._token_provider,
            client=self._client,
            timeout_seconds=self._timeout,
            json_body={"userPromptData": {"text": text}},
        )
        result = payload.get("sanitizationResult")
        if not isinstance(result, dict):
            raise GovernanceUnavailableError("Model Armor returned no sanitization result.")
        invocation = result.get("invocationResult")
        match_state = result.get("filterMatchState")
        if invocation != "SUCCESS" or match_state not in {"MATCH_FOUND", "NO_MATCH_FOUND"}:
            raise GovernanceUnavailableError("Model Armor did not return a complete decision.")
        categories = tuple(sorted(_matched_filter_names(result.get("filterResults"))))
        return PromptScreeningResult(
            provider="google-cloud-model-armor",
            blocked=match_state == "MATCH_FOUND",
            categories=categories,
            input_hash=sha256_digest({"text": text}),
            invocation_result=str(invocation),
            template_reference=self._template,
        )


class StaticIncidentMemory:
    """Tenant-scoped, cited incident-memory fixture for deterministic local runs."""

    def __init__(self) -> None:
        resource = files("changeops_agent_fleet.seed").joinpath("incident_memories.json")
        document = json.loads(resource.read_text(encoding="utf-8"))
        records = document.get("incidents")
        if not isinstance(records, list):
            raise ValueError("incident memory seed must contain an incidents list")
        self._records: tuple[dict[str, Any], ...] = tuple(
            record for record in records if isinstance(record, dict)
        )

    async def retrieve(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]:
        query_tokens = _search_tokens(
            f"{event.subject.system_id} {event.change.summary} "
            f"{event.change.old_version} {event.change.new_version}"
        )
        ranked: list[tuple[int, dict[str, Any], tuple[str, ...]]] = []
        for record in self._records:
            searchable = json.dumps(record, sort_keys=True)
            matched = tuple(sorted(query_tokens & _search_tokens(searchable)))
            if len(matched) >= 2:
                ranked.append((len(matched), record, matched))
        evidence: list[EvidenceItem] = []
        for _, record, matched in sorted(ranked, key=lambda item: item[0], reverse=True)[:3]:
            incident_id = str(record["incident_id"])
            attributes: dict[str, JsonValue] = {
                "incident_id": incident_id,
                "outcome": str(record["outcome"]),
                "lessons": [str(item) for item in record.get("lessons", [])],
                "matched_terms": list(matched),
                "source_reference": str(record["source_reference"]),
            }
            evidence.append(
                EvidenceItem(
                    evidence_id=f"memory-{incident_id}",
                    tenant_id=event.tenant_id,
                    source_system="local-incident-memory",
                    source_resource=f"memory://tenant/{event.tenant_id}/incidents/{incident_id}",
                    summary=(
                        f"Prior incident {incident_id} is relevant; historical memory is "
                        "untrusted until corroborated."
                    ),
                    content_hash=sha256_digest(attributes),
                    trust=EvidenceTrust.UNTRUSTED,
                    observed_at=event.received_at,
                    attributes=attributes,
                )
            )
        return tuple(evidence)


class VertexMemoryBankRetriever:
    """Vertex AI Memory Bank retrieve REST adapter with exact tenant scope."""

    def __init__(
        self,
        *,
        memory_bank_id: str,
        token_provider: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        match = _MEMORY_BANK.fullmatch(memory_bank_id)
        if match is None:
            raise ValueError("MEMORY_BANK_ID must be a full Reasoning Engine resource name.")
        self._memory_bank_id = memory_bank_id
        self._location = match.group("location")
        self._token_provider = token_provider
        self._client = client
        self._timeout = timeout_seconds

    async def retrieve(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]:
        endpoint = (
            f"https://{self._location}-aiplatform.googleapis.com/v1beta1/"
            f"{self._memory_bank_id}/memories:retrieve"
        )
        payload = await _authorized_json(
            method="POST",
            url=endpoint,
            token_provider=self._token_provider,
            client=self._client,
            timeout_seconds=self._timeout,
            json_body={"scope": {"tenant_id": event.tenant_id}},
        )
        retrieved = payload.get("retrievedMemories", [])
        if not isinstance(retrieved, list):
            raise GovernanceUnavailableError("Memory Bank returned an invalid memory list.")
        evidence: list[EvidenceItem] = []
        for item in retrieved[:3]:
            memory = item.get("memory") if isinstance(item, dict) else None
            if not isinstance(memory, dict):
                continue
            name = memory.get("name")
            fact = memory.get("fact")
            if not isinstance(name, str) or not isinstance(fact, str):
                continue
            memory_id = name.rsplit("/", maxsplit=1)[-1]
            attributes: dict[str, JsonValue] = {"memory_name": name, "fact": fact}
            evidence.append(
                EvidenceItem(
                    evidence_id=f"memory-{memory_id}",
                    tenant_id=event.tenant_id,
                    source_system="vertex-ai-memory-bank",
                    source_resource=f"memory://tenant/{event.tenant_id}/managed/{memory_id}",
                    summary="Retrieved tenant-scoped historical memory for corroboration.",
                    content_hash=sha256_digest(attributes),
                    trust=EvidenceTrust.UNTRUSTED,
                    observed_at=datetime.now(UTC),
                    attributes=attributes,
                )
            )
        return tuple(evidence)


class AgentRegistryProbe:
    """Read-only Agent Registry v1 visibility probe."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        token_provider: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._parent = f"projects/{project}/locations/{location}"
        self._token_provider = token_provider
        self._client = client

    async def visible_agent_ids(self) -> tuple[str, ...]:
        payload = await _authorized_json(
            method="GET",
            url=f"https://agentregistry.googleapis.com/v1/{self._parent}/agents",
            token_provider=self._token_provider,
            client=self._client,
            timeout_seconds=10.0,
        )
        agents = payload.get("agents", [])
        if not isinstance(agents, list):
            raise GovernanceUnavailableError("Agent Registry returned an invalid agent list.")
        identifiers = []
        for agent in agents:
            if isinstance(agent, dict) and isinstance(agent.get("name"), str):
                identifiers.append(agent["name"].rsplit("/", maxsplit=1)[-1])
        return tuple(sorted(set(identifiers)))


class SecretManagerResolver:
    """Secret Manager REST resolver that verifies CRC32C and never logs payloads."""

    def __init__(
        self,
        *,
        project: str,
        token_provider: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project = project
        self._token_provider = token_provider
        self._client = client

    async def access(self, secret_id: str, *, version: str = "latest") -> bytes:
        if _RESOURCE_ID.fullmatch(secret_id) is None or _RESOURCE_ID.fullmatch(version) is None:
            raise ValueError("Secret and version identifiers contain unsupported characters.")
        payload = await _authorized_json(
            method="GET",
            url=(
                "https://secretmanager.googleapis.com/v1/projects/"
                f"{self._project}/secrets/{secret_id}/versions/{version}:access"
            ),
            token_provider=self._token_provider,
            client=self._client,
            timeout_seconds=10.0,
        )
        secret_payload = payload.get("payload")
        if not isinstance(secret_payload, dict):
            raise GovernanceUnavailableError("Secret Manager returned no payload.")
        encoded = secret_payload.get("data")
        expected_crc = secret_payload.get("dataCrc32c")
        if not isinstance(encoded, str) or not isinstance(expected_crc, str | int):
            raise GovernanceUnavailableError("Secret Manager returned incomplete integrity data.")
        try:
            data = base64.b64decode(encoded, validate=True)
            expected = int(expected_crc)
        except (ValueError, TypeError) as error:
            raise GovernanceUnavailableError(
                "Secret Manager returned invalid payload encoding."
            ) from error
        checksum_factory: Any = google_crc32c.Checksum
        checksum = checksum_factory(data)
        if int(checksum.hexdigest(), 16) != expected:
            raise GovernanceUnavailableError("Secret Manager payload checksum verification failed.")
        return data


class ScopedIdentityResolver:
    """Distinct local, Agent Identity, or least-privilege service-account references."""

    def __init__(
        self,
        *,
        mode: str,
        agent_identity_prefix: str | None = None,
        service_account_domain: str | None = None,
    ) -> None:
        self._mode = mode
        self._prefix = agent_identity_prefix.rstrip("/") if agent_identity_prefix else None
        self._domain = service_account_domain

    def reference(self, tenant_id: str, agent_id: str) -> str:
        if self._mode == "local":
            return f"identity://local/{tenant_id}/{agent_id}-v1"
        if self._mode == "agent_identity" and self._prefix:
            return f"{self._prefix}/{agent_id}"
        if self._mode == "service_account" and self._domain:
            return f"serviceAccount:changeops-{agent_id}@{self._domain}"
        raise GovernanceUnavailableError("The configured agent identity mode is incomplete.")


class GovernanceService:
    """One fail-closed boundary invoked before evidence and model execution."""

    def __init__(
        self,
        *,
        prompt_guard: PromptGuard,
        memory_retriever: MemoryRetriever,
        identity_resolver: IdentityResolver,
    ) -> None:
        self._prompt_guard = prompt_guard
        self._memory_retriever = memory_retriever
        self._identity_resolver = identity_resolver

    async def prepare(self, event: ChangeEvent) -> tuple[EvidenceItem, ...]:
        screening = await self._prompt_guard.screen(event.change.summary)
        if screening.blocked:
            raise PromptBlockedError(screening)
        return await self._memory_retriever.retrieve(event)

    def identity_reference(self, tenant_id: str, agent_id: str) -> str:
        return self._identity_resolver.reference(tenant_id, agent_id)


def build_governance(settings: Settings) -> GovernanceService:
    """Build exactly one explicit local or managed adapter set."""

    identity = ScopedIdentityResolver(
        mode=settings.agent_identity_mode.value,
        agent_identity_prefix=settings.agent_identity_prefix,
        service_account_domain=settings.agent_service_account_domain,
    )
    if settings.governance_backend is GovernanceBackend.LOCAL:
        return GovernanceService(
            prompt_guard=DeterministicPromptGuard(),
            memory_retriever=StaticIncidentMemory(),
            identity_resolver=identity,
        )
    if settings.model_armor_template is None or settings.memory_bank_id is None:
        raise GovernanceUnavailableError("Managed governance settings were not validated.")
    token_provider = GoogleAuthTokenProvider()
    return GovernanceService(
        prompt_guard=ModelArmorPromptGuard(
            template=settings.model_armor_template,
            token_provider=token_provider,
        ),
        memory_retriever=VertexMemoryBankRetriever(
            memory_bank_id=settings.memory_bank_id,
            token_provider=token_provider,
        ),
        identity_resolver=identity,
    )


async def _authorized_json(
    *,
    method: str,
    url: str,
    token_provider: AccessTokenProvider,
    client: httpx.AsyncClient | None,
    timeout_seconds: float,
    json_body: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    resolved = client or httpx.AsyncClient(timeout=timeout_seconds)
    try:
        token = await token_provider.token()
        response = await resolved.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
        if response.status_code >= 400:
            raise GovernanceUnavailableError(
                f"Managed governance request failed with HTTP {response.status_code}."
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GovernanceUnavailableError("Managed governance returned a non-object response.")
        return payload
    except (httpx.TimeoutException, httpx.NetworkError, ValueError) as error:
        raise GovernanceUnavailableError("Managed governance request was unavailable.") from error
    finally:
        if owns_client:
            await resolved.aclose()


def _matched_filter_names(value: object) -> set[str]:
    matched: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, dict) and _contains_match(child):
                matched.add(str(key))
    return matched


def _contains_match(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "matchState" and child == "MATCH_FOUND") or _contains_match(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_match(item) for item in value)
    return False


def _search_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", value.casefold())
        if len(token) >= 3 and token not in {"the", "and", "from", "with", "change"}
    }
