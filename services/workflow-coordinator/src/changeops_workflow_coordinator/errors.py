"""Workflow error classification and stable API failures."""

from fastapi import status


class WorkflowError(RuntimeError):
    def __init__(self, code: str, detail: str, *, transient: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.transient = transient


class WorkflowTransientError(WorkflowError):
    def __init__(self, code: str = "TRANSIENT_DEPENDENCY") -> None:
        super().__init__(code, "A workflow dependency is temporarily unavailable.", transient=True)


class WorkflowPermanentError(WorkflowError):
    def __init__(self, code: str = "PERMANENT_WORKFLOW_FAILURE") -> None:
        super().__init__(code, "The workflow cannot continue automatically.", transient=False)


class WorkflowApiError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class WorkflowNotFoundError(WorkflowApiError):
    def __init__(self) -> None:
        super().__init__(
            "NOT_FOUND",
            "The requested workflow was not found.",
            status.HTTP_404_NOT_FOUND,
        )


class WorkflowConflictError(WorkflowApiError):
    def __init__(self, detail: str = "The workflow version is stale.") -> None:
        super().__init__("WORKFLOW_CONFLICT", detail, status.HTTP_409_CONFLICT)


class CallbackAuthenticationError(WorkflowApiError):
    def __init__(self) -> None:
        super().__init__(
            "CALLBACK_AUTHENTICATION_FAILED",
            "A valid workflow callback credential is required.",
            status.HTTP_401_UNAUTHORIZED,
        )
