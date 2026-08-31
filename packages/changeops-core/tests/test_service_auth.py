import base64
import json

import pytest
from changeops_core import (
    GoogleCloudServiceAuthProvider,
    NoopServiceAuthProvider,
    ServiceAuthenticationError,
    ServiceAuthMode,
    Settings,
    build_service_auth_provider,
    service_audience,
)


def _token(expiry: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.mark.asyncio
async def test_google_cloud_provider_uses_serverless_header_and_caches_by_origin() -> None:
    audiences: list[str] = []
    provider = GoogleCloudServiceAuthProvider(
        token_fetcher=lambda audience: audiences.append(audience) or _token(2_000),
        clock=lambda: 1_000,
    )

    first = await provider.headers("https://service.example.run.app/v1/items")
    second = await provider.headers("https://service.example.run.app/v1/other")

    assert first == {"X-Serverless-Authorization": f"Bearer {_token(2_000)}"}
    assert second == first
    assert audiences == ["https://service.example.run.app"]


@pytest.mark.asyncio
async def test_google_cloud_provider_fails_closed_for_invalid_token() -> None:
    provider = GoogleCloudServiceAuthProvider(
        token_fetcher=lambda _: "invalid", clock=lambda: 1_000
    )

    with pytest.raises(ServiceAuthenticationError):
        await provider.headers("https://service.example.run.app")


def test_service_audience_rejects_insecure_or_credentialed_urls() -> None:
    assert (
        service_audience("https://service.example.run.app/path")
        == "https://service.example.run.app"
    )
    with pytest.raises(ValueError):
        service_audience("http://service.example.run.app")
    with pytest.raises(ValueError):
        service_audience("https://user:password@service.example.run.app")


@pytest.mark.asyncio
async def test_local_provider_adds_no_platform_authorization() -> None:
    provider = build_service_auth_provider(
        Settings(SERVICE_AUTH_MODE=ServiceAuthMode.NONE, _env_file=None)
    )
    assert isinstance(provider, NoopServiceAuthProvider)
    assert await provider.headers("http://127.0.0.1:8000") == {}
