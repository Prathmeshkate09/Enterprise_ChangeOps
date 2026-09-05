"""Admission security tests with explicit injected identities, never runtime bypasses."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from changeops_core import Settings
from changeops_persistence import InMemoryChangeStateRepository
from control_api.admission.models import Identity, InvitationCreate, Role, StatusUpdate
from control_api.admission.service import AdmissionService, user_key
from control_api.admission.store import MemoryStore, MemoryTransaction
from control_api.app import create_app
from control_api.errors import ControlApiError
from fastapi.testclient import TestClient

OWNER = Identity(subject="owner", email="owner@example.test", mfa=True)
ALICE = Identity(subject="alice", email="alice@example.test")
BOB = Identity(subject="bob", email="bob@example.test")


@pytest.fixture
def service() -> AdmissionService:
    result = AdmissionService(MemoryStore())
    result.bootstrap_owner(OWNER.subject)
    return result


def admit(service: AdmissionService, identity: Identity, role: Role = Role.AUDITOR) -> str:
    organization = service.create_organization(OWNER, "Example enterprise")
    _, token = service.invite(
        OWNER,
        InvitationCreate(
            email=identity.email,
            organization_id=organization.organization_id,
            role=role,
        ),
    )
    service.redeem(identity, token)
    return organization.organization_id


def test_login_does_not_grant_access_and_owner_has_no_implicit_tenant_access(
    service: AdmissionService,
) -> None:
    assert service.access(ALICE).status == "not_admitted"
    organization_id = admit(service, ALICE)
    with pytest.raises(ControlApiError):
        service.workspace(OWNER, organization_id)
    with pytest.raises(ControlApiError):
        service.workspace(BOB, organization_id)
    assert service.workspace(ALICE, organization_id).membership.role == Role.AUDITOR


def test_organization_admin_cannot_invite_or_create_organizations(
    service: AdmissionService,
) -> None:
    organization_id = admit(service, ALICE, Role.ORGANIZATION_ADMIN)
    with pytest.raises(ControlApiError):
        service.invite(
            ALICE,
            InvitationCreate(email=BOB.email, organization_id=organization_id, role=Role.APPROVER),
        )
    with pytest.raises(ControlApiError):
        service.create_organization(ALICE, "Unauthorized organization")
    with pytest.raises(ControlApiError):
        service.list_records(ALICE, "users")


def test_admin_must_use_mfa(service: AdmissionService) -> None:
    no_mfa = OWNER.model_copy(update={"mfa": False})
    assert service.access(no_mfa).status == "mfa_required"
    with pytest.raises(ControlApiError):
        service.create_organization(no_mfa, "Forbidden")


def test_invitation_is_email_bound_single_use_and_not_stored_as_plaintext(
    service: AdmissionService,
) -> None:
    org = service.create_organization(OWNER, "Example")
    _, token = service.invite(
        OWNER,
        InvitationCreate(
            email=ALICE.email, organization_id=org.organization_id, role=Role.REQUESTER
        ),
    )
    with pytest.raises(ControlApiError):
        service.redeem(BOB, token)
    assert service.access(ALICE).status == "not_admitted"
    assert service.redeem(ALICE, token).status == "active"
    with pytest.raises(ControlApiError):
        service.redeem(ALICE, token)
    assert token not in str(service.store.list("admission_invitations"))
    assert token not in str(service.store.list("admission_audit"))
    assert ALICE.email not in str(service.store.list("admission_audit"))


def test_expired_invitation_fails_without_creating_membership(service: AdmissionService) -> None:
    now = datetime.now(UTC)
    service.clock = lambda: now
    org = service.create_organization(OWNER, "Example")
    _, token = service.invite(
        OWNER,
        InvitationCreate(email=ALICE.email, organization_id=org.organization_id, role=Role.AUDITOR),
    )
    service.clock = lambda: now + timedelta(hours=24)
    with pytest.raises(ControlApiError):
        service.redeem(ALICE, token)
    assert service.access(ALICE).workspaces == ()


def test_concurrent_redemption_has_one_winner(service: AdmissionService) -> None:
    org = service.create_organization(OWNER, "Example")
    _, token = service.invite(
        OWNER,
        InvitationCreate(email=ALICE.email, organization_id=org.organization_id, role=Role.AUDITOR),
    )

    def redeem() -> bool:
        try:
            service.redeem(ALICE, token)
            return True
        except ControlApiError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))
    assert results.count(True) == 1
    assert len(service.access(ALICE).workspaces) == 1


def test_suspension_invalidates_access_without_waiting_for_token_expiry(
    service: AdmissionService,
) -> None:
    org_id = admit(service, ALICE)
    service.set_status(
        OWNER, "organizations", org_id, StatusUpdate(active=False, expected_version=1)
    )
    with pytest.raises(ControlApiError):
        service.workspace(ALICE, org_id)
    service.set_status(
        OWNER, "organizations", org_id, StatusUpdate(active=True, expected_version=2)
    )
    user = service.list_records(OWNER, "users")
    alice = next(item for item in user if item["subject"] == ALICE.subject)
    service.set_status(
        OWNER,
        "users",
        user_key(ALICE.subject),
        StatusUpdate(active=False, expected_version=alice["version"]),
    )
    assert service.access(ALICE).status == "suspended"
    with pytest.raises(ControlApiError):
        service.workspace(ALICE, org_id)


def test_stale_update_and_owner_lockout_are_rejected(service: AdmissionService) -> None:
    org_id = admit(service, ALICE)
    with pytest.raises(ControlApiError, match="Refresh"):
        service.set_status(
            OWNER, "organizations", org_id, StatusUpdate(active=False, expected_version=50)
        )
    with pytest.raises(ControlApiError):
        service.set_status(
            OWNER, "users", user_key(OWNER.subject), StatusUpdate(active=False, expected_version=1)
        )


def test_audit_failure_rolls_back_admission(
    service: AdmissionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = MemoryTransaction.put

    def failing_put(self: MemoryTransaction, path: str, document: dict[str, object]) -> None:
        if path.startswith("admission_audit/"):
            raise RuntimeError("simulated audit storage outage")
        original(self, path, document)

    monkeypatch.setattr(MemoryTransaction, "put", failing_put)
    with pytest.raises(RuntimeError, match="audit storage outage"):
        service.create_organization(OWNER, "Must not persist")
    assert service.store.list("admission_organizations") == []


def test_second_bootstrap_and_invitation_role_overwrite_are_rejected(
    service: AdmissionService,
) -> None:
    with pytest.raises(ControlApiError):
        service.bootstrap_owner(BOB.subject)
    org_id = admit(service, ALICE)
    _, token = service.invite(
        OWNER,
        InvitationCreate(email=ALICE.email, organization_id=org_id, role=Role.ORGANIZATION_ADMIN),
    )
    with pytest.raises(ControlApiError):
        service.redeem(ALICE, token)
    assert service.workspace(ALICE, org_id).membership.role == Role.AUDITOR


class TestIdentityProvider:
    """Only dependency-injected into tests; not selected by environment configuration."""

    __test__ = False

    def verify(self, session: str) -> Identity:
        if session == "owner-fixture":
            return OWNER
        if session == "alice-fixture":
            return ALICE
        if session == "bob-fixture":
            return BOB
        raise ControlApiError("session_invalid", "Invalid test session.", 401)

    def create_session(self, id_token: str) -> str:
        self.verify(id_token)
        return id_token

    def revoke(self, subject: str) -> None:
        return None


def test_enterprise_http_boundary_blocks_legacy_headers(service: AdmissionService) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        ENTERPRISE_ACCESS_ENABLED=True,
        IDENTITY_PLATFORM_PROJECT="test-project",
        GOOGLE_CLOUD_PROJECT="test-project",
        PERSISTENCE_BACKEND="firestore",
    )
    app = create_app(
        settings=settings,
        repository=InMemoryChangeStateRepository(),
        admission_service=service,
        identity_provider=TestIdentityProvider(),
    )
    with TestClient(app) as client:
        assert client.get("/v1/access/me").status_code == 401
        assert (
            client.get("/v1/changes", headers={"X-Tenant-ID": "other-company"}).status_code == 404
        )
        assert (
            client.post(
                "/v1/demo/events/api-breaking-change", headers={"X-Tenant-ID": "other-company"}
            ).status_code
            == 404
        )
        headers = {"Authorization": "Bearer alice-fixture"}
        assert client.get("/v1/access/admin/users", headers=headers).status_code == 403
        assert client.get("/v1/access/me", headers=headers).json()["status"] == "not_admitted"
        assert client.get("/v1/access/me", headers=headers).headers["cache-control"] == "no-store"
        org = client.post(
            "/v1/access/admin/organizations",
            headers={"Authorization": "Bearer owner-fixture"},
            json={"name": "Test organization"},
        )
        assert org.status_code == 201
        assert (
            client.get(
                f"/v1/access/organizations/{org.json()['organization_id']}", headers=headers
            ).status_code
            == 403
        )


def test_enterprise_configuration_cannot_fall_back_to_memory() -> None:
    with pytest.raises(ValueError, match="Firestore"):
        Settings(_env_file=None, ENTERPRISE_ACCESS_ENABLED=True, IDENTITY_PLATFORM_PROJECT="test")


def test_only_owner_can_appoint_admin_and_revocation_is_immediate(
    service: AdmissionService,
) -> None:
    admit(service, ALICE)
    target = next(
        user for user in service.list_records(OWNER, "users") if user["subject"] == ALICE.subject
    )
    service.set_administrator(
        OWNER,
        user_key(ALICE.subject),
        StatusUpdate(active=True, expected_version=target["version"]),
    )
    assert not service.access(ALICE).platform_admin
    privileged = ALICE.model_copy(update={"mfa": True})
    assert service.access(privileged).platform_admin
    assert not service.access(privileged).owner
    with pytest.raises(ControlApiError):
        service.set_administrator(
            privileged, user_key(BOB.subject), StatusUpdate(active=True, expected_version=1)
        )
    service.set_administrator(
        OWNER,
        user_key(ALICE.subject),
        StatusUpdate(active=False, expected_version=target["version"] + 1),
    )
    assert not service.access(privileged).platform_admin
    with pytest.raises(ControlApiError):
        service.create_organization(privileged, "No longer authorized")


def test_admission_pagination_is_bounded_and_does_not_repeat(service: AdmissionService) -> None:
    for index in range(52):
        service.create_organization(OWNER, f"Organization {index}")
    first = service.list_records(OWNER, "organizations")
    second = service.list_records(OWNER, "organizations", after=first[-1]["record_id"])
    assert len(first) == 50
    assert len(second) == 2
    assert {row["record_id"] for row in first}.isdisjoint(row["record_id"] for row in second)
