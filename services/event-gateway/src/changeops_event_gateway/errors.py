"""Stable Event Gateway problem errors."""

from fastapi import status


class EventGatewayError(RuntimeError):
    def __init__(self, *, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class SignatureError(EventGatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_SIGNATURE",
            detail="A valid webhook signature is required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class EventConflictError(EventGatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="EVENT_IDEMPOTENCY_CONFLICT",
            detail="The event identifier was already used for different content.",
            status_code=status.HTTP_409_CONFLICT,
        )


class EventRateLimitedError(EventGatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="RATE_LIMITED",
            detail="The tenant event-ingestion rate limit is exhausted.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class EventDependencyError(EventGatewayError):
    def __init__(self, code: str = "EVENT_DEPENDENCY_UNAVAILABLE") -> None:
        super().__init__(
            code=code,
            detail="Event persistence or publication is temporarily unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
