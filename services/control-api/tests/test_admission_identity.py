"""SDK boundary tests; these do not claim a real Identity Platform sign-in passed."""

import time
from typing import Any
from unittest.mock import Mock

import pytest
from control_api.admission.identity import GoogleIdentityProvider
from control_api.errors import ControlApiError
from firebase_admin import auth, exceptions


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> GoogleIdentityProvider:
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    monkeypatch.setattr("firebase_admin.get_app", lambda name: object())
    return GoogleIdentityProvider("test-project")


def claims() -> dict[str, Any]:
    return {
        "sub": "user",
        "email": "user@example.test",
        "email_verified": True,
        "auth_time": int(time.time()),
        "firebase": {"sign_in_provider": "google.com"},
    }


@pytest.mark.parametrize(
    "update",
    [
        {"email_verified": False},
        {"email": None},
        {"sub": None},
        {"firebase": None},
        {"firebase": {"sign_in_provider": "anonymous"}},
        {"firebase": {"sign_in_provider": "custom"}},
        {"firebase": {"tenant": "unconfigured-identity-tenant"}},
    ],
)
def test_untrusted_identity_claims_rejected(update: dict[str, Any]) -> None:
    with pytest.raises(ControlApiError):
        GoogleIdentityProvider._identity({**claims(), **update})


def test_runtime_rejects_auth_emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    with pytest.raises(ValueError, match="emulator"):
        GoogleIdentityProvider("test-project")


def test_verify_requires_revocation_check(
    provider: GoogleIdentityProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify = Mock(return_value=claims())
    monkeypatch.setattr(auth, "verify_session_cookie", verify)
    assert provider.verify("fixture-cookie").subject == "user"
    assert verify.call_args.kwargs["check_revoked"] is True


def test_recent_login_required_for_cookie(
    provider: GoogleIdentityProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth, "verify_id_token", Mock(return_value={**claims(), "auth_time": time.time() - 600})
    )
    create = Mock()
    monkeypatch.setattr(auth, "create_session_cookie", create)
    with pytest.raises(ControlApiError, match="Sign in again"):
        provider.create_session("fixture-token")
    create.assert_not_called()


def test_identity_outage_does_not_fall_back(
    provider: GoogleIdentityProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "verify_session_cookie",
        Mock(side_effect=exceptions.UnavailableError("fixture outage")),
    )
    with pytest.raises(ControlApiError) as result:
        provider.verify("fixture-cookie")
    assert result.value.status_code == 503


def test_logout_propagates_revocation_failure(
    provider: GoogleIdentityProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "revoke_refresh_tokens",
        Mock(side_effect=exceptions.UnavailableError("fixture outage")),
    )
    with pytest.raises(ControlApiError) as result:
        provider.revoke("user")
    assert result.value.status_code == 503
