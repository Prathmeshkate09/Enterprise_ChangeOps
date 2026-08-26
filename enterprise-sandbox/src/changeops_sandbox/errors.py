"""Stable sandbox errors mapped to versioned API responses."""


class SandboxError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TenantRequiredError(SandboxError):
    def __init__(self) -> None:
        super().__init__("tenant_required", "X-Tenant-ID is required.", 401)


class SnapshotNotFoundError(SandboxError):
    def __init__(self, snapshot_id: str) -> None:
        super().__init__("snapshot_not_found", f"Snapshot {snapshot_id!r} was not found.", 404)


class TenantScopeError(SandboxError):
    def __init__(self) -> None:
        super().__init__("tenant_scope_violation", "The resource is outside tenant scope.", 403)


class PatchConflictError(SandboxError):
    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(
            "patch_conflict",
            f"Expected source field {expected!r}, found {actual!r}.",
            409,
        )


class ContractVersionNotFoundError(SandboxError):
    def __init__(self, version: str) -> None:
        super().__init__(
            "contract_version_not_found",
            f"Contract version {version!r} was not found.",
            404,
        )


class TransientSandboxError(SandboxError):
    def __init__(self) -> None:
        super().__init__(
            "transient_sandbox_failure",
            "Injected transient analytics failure; retry the same idempotency key.",
            503,
        )
