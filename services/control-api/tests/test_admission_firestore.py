"""Run only against an explicitly configured loopback emulator and unique test project."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from control_api.admission.models import (
    Identity,
    InvitationCreate,
    InvitationRevoke,
    MembershipUpdate,
    Role,
    StatusUpdate,
)
from control_api.admission.service import AdmissionService, user_key
from control_api.admission.store import FirestoreStore
from control_api.errors import ControlApiError
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore


def test_firestore_admission_survives_restart_and_serializes_redemption() -> None:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST is not configured")
    if not host.startswith(("127.0.0.1:", "localhost:")):
        pytest.fail("Admission integration test requires a loopback emulator")
    project = f"demo-admission-{uuid4().hex[:16]}"

    def fresh() -> AdmissionService:
        return AdmissionService(
            FirestoreStore(
                firestore.Client(
                    project=project,
                    credentials=AnonymousCredentials(),
                )
            )
        )

    owner = Identity(subject="fixture-owner", email="owner@example.test", mfa=True)
    member = Identity(subject="fixture-member", email="member@example.test")
    service = fresh()
    service.bootstrap_owner(owner.subject)
    org = service.create_organization(owner, "Emulator test organization")
    _, token = service.invite(
        owner,
        InvitationCreate(
            email=member.email,
            organization_id=org.organization_id,
            role=Role.AUDITOR,
        ),
    )

    def redeem() -> bool:
        try:
            fresh().redeem(member, token)
            return True
        except ControlApiError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))
    assert results.count(True) == 1
    assert fresh().workspace(member, org.organization_id).membership.role == Role.AUDITOR
    with pytest.raises(ControlApiError):
        fresh().workspace(owner, org.organization_id)
    # Exercise Firestore document-reference cursor, including an empty next page.
    rows = fresh().list_records(owner, "organizations")
    assert len(rows) == 1
    assert fresh().list_records(owner, "organizations", after=rows[-1]["record_id"]) == []
    fresh().update_membership(
        owner,
        org.organization_id,
        user_key(member.subject),
        MembershipUpdate(active=False, role=Role.APPROVER, expected_version=1),
    )
    with pytest.raises(ControlApiError):
        fresh().workspace(member, org.organization_id)
    fresh().update_membership(
        owner,
        org.organization_id,
        user_key(member.subject),
        MembershipUpdate(active=True, role=Role.APPROVER, expected_version=2),
    )
    assert fresh().workspace(member, org.organization_id).membership.role == Role.APPROVER
    members = fresh().list_members(owner, org.organization_id)
    assert members[0]["version"] == 3
    assert fresh().list_members(owner, org.organization_id, after=members[0]["record_id"]) == []
    invitation, token = fresh().invite(
        owner,
        InvitationCreate(
            email="new@example.test",
            organization_id=org.organization_id,
            role=Role.AUDITOR,
        ),
    )
    record = next(
        item
        for item in fresh().list_records(owner, "invitations")
        if item["invitation_id"] == invitation.invitation_id
    )
    fresh().revoke_invitation(owner, record["record_id"], InvitationRevoke(expected_version=1))
    with pytest.raises(ControlApiError):
        fresh().redeem(Identity(subject="new", email="new@example.test"), token)
    fresh().set_status(
        owner, "organizations", org.organization_id, StatusUpdate(active=False, expected_version=1)
    )
    with pytest.raises(ControlApiError):
        fresh().workspace(member, org.organization_id)
    assert len(fresh().list_records(owner, "audit")) == 9
    # No cleanup calls: emulator-only project is unique; never enumerate/delete shared records.
