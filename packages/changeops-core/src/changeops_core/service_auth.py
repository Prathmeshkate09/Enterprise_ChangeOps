"""Fail-closed identity tokens for private Google Cloud service calls."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol, cast
from urllib.parse import urlsplit

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import fetch_id_token

from changeops_core.config import ServiceAuthMode, Settings


class ServiceAuthenticationError(RuntimeError):
    """Raised when a managed caller identity cannot be obtained safely."""


class ServiceAuthProvider(Protocol):
    async def headers(self, audience: str) -> Mapping[str, str]: ...


class NoopServiceAuthProvider:
    """Local adapter that deliberately adds no platform authorization."""

    async def headers(self, audience: str) -> Mapping[str, str]:
        del audience
        return {}


def service_audience(url: str) -> str:
    """Return a strict HTTPS origin suitable for a Cloud Run token audience."""

    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Managed service audiences must be credential-free HTTPS URLs.")
    return f"https://{parsed.netloc}"


def _default_token_fetcher(audience: str) -> str:
    return cast(str, fetch_id_token(GoogleAuthRequest(), audience))  # type: ignore[no-untyped-call]


def _token_expiry(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        expiry = decoded["exp"]
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ServiceAuthenticationError(
            "Google Cloud returned an invalid identity token."
        ) from error
    if not isinstance(expiry, int | float):
        raise ServiceAuthenticationError("Google Cloud identity token expiry is invalid.")
    return float(expiry)


class GoogleCloudServiceAuthProvider:
    """Acquire and cache Google-signed ID tokens without service-account keys."""

    def __init__(
        self,
        *,
        token_fetcher: Callable[[str], str] = _default_token_fetcher,
        clock: Callable[[], float] = time.time,
        refresh_margin_seconds: float = 300.0,
    ) -> None:
        self._token_fetcher = token_fetcher
        self._clock = clock
        self._refresh_margin = refresh_margin_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    async def headers(self, audience: str) -> Mapping[str, str]:
        normalized = service_audience(audience)
        token = await asyncio.to_thread(self._token, normalized)
        return {"X-Serverless-Authorization": f"Bearer {token}"}

    def _token(self, audience: str) -> str:
        with self._lock:
            cached = self._tokens.get(audience)
            if cached is not None and cached[1] - self._refresh_margin > self._clock():
                return cached[0]
            try:
                token = self._token_fetcher(audience)
                expiry = _token_expiry(token)
            except ServiceAuthenticationError:
                raise
            except (GoogleAuthError, OSError, ValueError) as error:
                raise ServiceAuthenticationError(
                    "Google Cloud service identity is unavailable."
                ) from error
            if expiry <= self._clock():
                raise ServiceAuthenticationError("Google Cloud identity token is expired.")
            self._tokens[audience] = (token, expiry)
            return token


def build_service_auth_provider(settings: Settings) -> ServiceAuthProvider:
    if settings.service_auth_mode is ServiceAuthMode.GOOGLE_CLOUD:
        return GoogleCloudServiceAuthProvider()
    return NoopServiceAuthProvider()
