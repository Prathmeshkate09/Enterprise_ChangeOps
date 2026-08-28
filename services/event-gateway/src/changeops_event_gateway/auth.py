"""HMAC webhook authentication over the exact request bytes."""

import hashlib
import hmac

from changeops_event_gateway.errors import SignatureError


class WebhookSignatureVerifier:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Event webhook secret must contain at least 32 bytes.")
        self._secret = secret.encode("utf-8")

    def verify(self, body: bytes, signature: str | None) -> None:
        if signature is None or not signature.startswith("sha256="):
            raise SignatureError
        supplied = signature.removeprefix("sha256=")
        if len(supplied) != 64:
            raise SignatureError
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise SignatureError
