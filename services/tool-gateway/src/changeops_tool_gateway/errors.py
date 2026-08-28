"""Stable fail-closed Tool Gateway errors."""

from __future__ import annotations

from fastapi import status


class GatewayError(RuntimeError):
    def __init__(self, *, code: str, title: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.title = title
        self.detail = detail
        self.status_code = status_code


class AuthenticationError(GatewayError):
    def __init__(self, detail: str = "A valid authenticated identity is required.") -> None:
        super().__init__(
            code="AUTHENTICATION_REQUIRED",
            title="Authentication required",
            detail=detail,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(GatewayError):
    def __init__(self, detail: str = "The authenticated identity is not authorized.") -> None:
        super().__init__(
            code="AUTHORIZATION_DENIED",
            title="Authorization denied",
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ApprovalRequiredError(GatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="APPROVAL_REQUIRED",
            title="Approval required",
            detail="The requested tool action requires a current approval for the exact plan.",
            status_code=status.HTTP_409_CONFLICT,
        )


class PolicyDeniedError(GatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="POLICY_DENIED",
            title="Policy denied",
            detail="Deterministic policy denied the requested tool action.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class GatewayNotFoundError(GatewayError):
    def __init__(self, resource: str) -> None:
        super().__init__(
            code="NOT_FOUND",
            title="Resource not found",
            detail=f"The requested {resource} was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class GatewayConflictError(GatewayError):
    def __init__(self, detail: str, *, code: str = "CONFLICT") -> None:
        super().__init__(
            code=code,
            title="Conflict",
            detail=detail,
            status_code=status.HTTP_409_CONFLICT,
        )


class GatewayValidationError(GatewayError):
    def __init__(self, detail: str = "Tool arguments failed registered schema validation.") -> None:
        super().__init__(
            code="VALIDATION",
            title="Validation failed",
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class RateLimitedError(GatewayError):
    def __init__(self) -> None:
        super().__init__(
            code="RATE_LIMITED",
            title="Tool quota exceeded",
            detail="The tenant and tool concurrency quota is currently exhausted.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class ToolAdapterError(GatewayError):
    def __init__(self, *, code: str, detail: str, transient: bool) -> None:
        super().__init__(
            code=code,
            title="Tool execution failed",
            detail=detail,
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE if transient else status.HTTP_502_BAD_GATEWAY
            ),
        )
        self.transient = transient
