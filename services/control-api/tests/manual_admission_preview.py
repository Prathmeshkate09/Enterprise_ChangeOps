"""Explicit synthetic UI harness, not an application runtime or managed-login test.

Run directly for local review. Always binds loopback; has no environment-selected auth bypass.
Use only fixture session cookies owner-fixture/alice-fixture in the isolated preview browser.
"""

import uvicorn
from changeops_core import Settings
from changeops_persistence import InMemoryChangeStateRepository
from control_api.admission.models import Role
from control_api.admission.service import AdmissionService
from control_api.admission.store import MemoryStore
from control_api.app import create_app
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from test_admission import ALICE, OWNER, TestIdentityProvider, admit


def main() -> None:
    admission = AdmissionService(MemoryStore())
    admission.bootstrap_owner(OWNER.subject)
    admit(admission, ALICE, Role.ORGANIZATION_ADMIN)
    app = create_app(
        settings=Settings(
            _env_file=None,
            APP_ENV="test",
            ENTERPRISE_ACCESS_ENABLED=True,
            IDENTITY_PLATFORM_PROJECT="demo-ui-preview",
            GOOGLE_CLOUD_PROJECT="demo-ui-preview",
            PERSISTENCE_BACKEND="firestore",
        ),
        repository=InMemoryChangeStateRepository(),
        admission_service=admission,
        identity_provider=TestIdentityProvider(),
    )

    @app.get("/__fixture/{account}", include_in_schema=False)
    def fixture_login(account: str) -> RedirectResponse:
        # Only this manually invoked test harness exposes fixture switching.
        # No such route exists in create_app or any deployed service entry point.
        tokens = {"owner": "owner-fixture", "member": "alice-fixture", "pending": "bob-fixture"}
        if account not in tokens:
            raise HTTPException(status_code=404)
        response = RedirectResponse("http://127.0.0.1:3011/access-status", status_code=303)
        response.set_cookie(
            "changeops_session", tokens[account], httponly=True, samesite="strict", max_age=3600
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    uvicorn.run(app, host="127.0.0.1", port=8011, access_log=False)


if __name__ == "__main__":
    main()
