"""Short-lived HMAC identity adapter for local and test execution."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from changeops_policy_engine import IdentityKind, VerifiedIdentity

from changeops_tool_gateway.errors import AuthenticationError


class IdentityVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity:
        """Authenticate and validate a short-lived identity token."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise AuthenticationError("Identity token encoding is invalid.") from error


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class HmacIdentityVerifier:
    """Local adapter; managed workload identity replaces it in Phase 8."""

    def __init__(
        self,
        secret: str,
        audience: str,
        *,
        clock: Callable[[], datetime] | None = None,
        maximum_lifetime: timedelta = timedelta(hours=1),
    ) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Tool Gateway identity secret must contain at least 32 bytes.")
        if not audience.strip():
            raise ValueError("Tool Gateway identity audience is required.")
        self._secret = secret.encode("utf-8")
        self._audience = audience
        self._clock = clock or (lambda: datetime.now(UTC))
        self._maximum_lifetime = maximum_lifetime

    def issue(
        self,
        *,
        subject: str,
        tenant_id: str,
        kind: IdentityKind,
        roles: tuple[str, ...] = (),
        lifetime: timedelta = timedelta(minutes=15),
    ) -> str:
        now = self._clock()
        payload = {
            "aud": self._audience,
            "exp": int((now + lifetime).timestamp()),
            "iat": int(now.timestamp()),
            "kind": kind.value,
            "roles": list(roles),
            "sub": subject,
            "tenant_id": tenant_id,
        }
        header = {"alg": "HS256", "typ": "JWT"}
        encoded_header = _b64encode(
            json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        encoded_payload = _b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{encoded_header}.{encoded_payload}"
        signature = hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return f"{signing_input}.{_b64encode(signature)}"

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
        except ValueError as error:
            raise AuthenticationError("Identity token structure is invalid.") from error
        signing_input = f"{encoded_header}.{encoded_payload}"
        expected = hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        supplied = _b64decode(encoded_signature)
        if not hmac.compare_digest(expected, supplied):
            raise AuthenticationError("Identity token signature is invalid.")
        try:
            header = json.loads(
                _b64decode(encoded_header), object_pairs_hook=_reject_duplicate_keys
            )
            payload = json.loads(
                _b64decode(encoded_payload), object_pairs_hook=_reject_duplicate_keys
            )
            if header != {"alg": "HS256", "typ": "JWT"}:
                raise ValueError("unsupported token header")
            if not isinstance(payload, dict):
                raise ValueError("token claims must be an object")
            issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
            now = self._clock()
            if payload["aud"] != self._audience:
                raise ValueError("audience mismatch")
            if issued_at > now + timedelta(seconds=30):
                raise ValueError("token issued in the future")
            if expires_at <= now:
                raise ValueError("token expired")
            if expires_at - issued_at > self._maximum_lifetime:
                raise ValueError("token lifetime exceeds policy")
            return VerifiedIdentity(
                subject=payload["sub"],
                tenant_id=payload["tenant_id"],
                kind=payload["kind"],
                roles=tuple(payload.get("roles", ())),
                audience=payload["aud"],
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AuthenticationError("Identity token claims are invalid.") from error
