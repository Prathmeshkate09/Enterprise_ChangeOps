"""Stable tenant-facing Control API errors."""


class ControlApiError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TenantRequiredError(ControlApiError):
    def __init__(self) -> None:
        super().__init__("tenant_required", "A valid X-Tenant-ID is required.", 401)


class ActorRequiredError(ControlApiError):
    def __init__(self) -> None:
        super().__init__("actor_required", "A valid X-Actor-ID is required.", 401)
