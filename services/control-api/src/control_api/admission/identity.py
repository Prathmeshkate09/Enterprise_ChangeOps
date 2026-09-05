"""Google-managed session cookies; no development token verifier in the runtime."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from typing import Any, Protocol

import firebase_admin  # type: ignore[import-untyped]  # SDK does not publish py.typed.
from firebase_admin import auth, exceptions

from control_api.admission.models import Identity
from control_api.errors import ControlApiError


class IdentityProvider(Protocol):
    def verify(self, session: str) -> Identity: ...
    def create_session(self, id_token: str) -> str: ...
    def revoke(self, subject: str) -> None: ...


class GoogleIdentityProvider:
    def __init__(self, project: str) -> None:
        if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
            raise ValueError("Enterprise runtime must not trust Firebase emulator tokens.")
        name = f"admission-{project}"
        try:
            self._app = firebase_admin.get_app(name)
        except ValueError:
            self._app = firebase_admin.initialize_app(
                options={"projectId": project, "httpTimeout": 10}, name=name
            )

    @staticmethod
    def _identity(claims: dict[str, Any]) -> Identity:
        firebase = claims.get("firebase", {})
        if (
            claims.get("email_verified") is not True
            or not isinstance(claims.get("sub"), str)
            or not isinstance(claims.get("email"), str)
            or not isinstance(firebase, dict)
            or firebase.get("sign_in_provider") in {"anonymous", "custom"}
            or firebase.get("tenant") is not None
        ):
            raise ControlApiError("identity_rejected", "Use your verified invited account.", 401)
        return Identity(
            subject=claims["sub"],
            email=claims["email"],
            mfa=bool(firebase.get("sign_in_second_factor")),
        )

    def verify(self, session: str) -> Identity:
        try:
            claims = auth.verify_session_cookie(session, check_revoked=True, app=self._app)
            return self._identity(claims)
        except (
            auth.InvalidSessionCookieError,
            auth.RevokedSessionCookieError,
            auth.UserDisabledError,
            auth.UserNotFoundError,
            ValueError,
        ) as error:
            raise ControlApiError("session_invalid", "Sign in again to continue.", 401) from error
        except exceptions.FirebaseError as error:
            raise ControlApiError(
                "identity_unavailable", "Identity service is unavailable.", 503
            ) from error

    def create_session(self, id_token: str) -> str:
        try:
            claims = auth.verify_id_token(id_token, check_revoked=True, app=self._app)
            self._identity(claims)
            if not 0 <= time.time() - claims.get("auth_time", 0) < 300:
                raise ControlApiError("recent_login_required", "Sign in again to continue.", 401)
            cookie: str = auth.create_session_cookie(
                id_token,
                expires_in=timedelta(hours=8),
                app=self._app,
            )
            return cookie
        except (
            auth.InvalidIdTokenError,
            auth.RevokedIdTokenError,
            auth.UserDisabledError,
            auth.UserNotFoundError,
            ValueError,
        ) as error:
            raise ControlApiError(
                "identity_rejected", "Use your verified invited account.", 401
            ) from error
        except exceptions.FirebaseError as error:
            raise ControlApiError(
                "identity_unavailable", "Identity service is unavailable.", 503
            ) from error

    def revoke(self, subject: str) -> None:
        try:
            auth.revoke_refresh_tokens(subject, app=self._app)
        except exceptions.FirebaseError as error:
            raise ControlApiError(
                "identity_unavailable", "Session revocation failed.", 503
            ) from error
