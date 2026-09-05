"""Central admission policy. Provider login alone never activates membership."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from control_api.admission.models import (
    AccessView,
    AdmissionAudit,
    Identity,
    Invitation,
    InvitationCreate,
    Membership,
    Organization,
    StatusUpdate,
    User,
    Workspace,
)
from control_api.admission.store import Document, Store, Transaction
from control_api.errors import ControlApiError


def denied() -> ControlApiError:
    return ControlApiError("access_denied", "Access has not been granted for this operation.", 403)


def user_key(subject: str) -> str:
    return hashlib.sha256(subject.encode()).hexdigest()


def user_path(subject: str) -> str:
    return f"admission_users/{user_key(subject)}"


def member_path(organization_id: str, subject: str) -> str:
    return f"admission_organizations/{organization_id}/members/{user_key(subject)}"


def read_user(tx: Transaction, subject: str) -> User | None:
    document = tx.get(user_path(subject))
    return User.model_validate(document) if document is not None else None


def require_admin(tx: Transaction, identity: Identity) -> User:
    user = read_user(tx, identity.subject)
    if user is None or not user.active or not user.platform_admin or not identity.mfa:
        raise denied()
    return user


class AdmissionService:
    def __init__(self, store: Store, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def _audit(self, tx: Transaction, actor: str, action: str, resource_id: str) -> None:
        event = AdmissionAudit(
            event_id=f"access_{uuid4().hex}",
            actor=actor,
            action=action,
            resource_id=resource_id,
            occurred_at=self.clock(),
        )
        tx.put(f"admission_audit/{event.event_id}", event.model_dump(mode="json"))

    def bootstrap_owner(self, subject: str) -> None:
        """Offline command only. A durable singleton prevents a second bootstrap."""

        def operation(tx: Transaction) -> None:
            if tx.get("admission_metadata/bootstrap") is not None or read_user(tx, subject):
                raise ControlApiError("already_bootstrapped", "Owner is already initialized.", 409)
            user = User(subject=subject, owner=True, platform_admin=True)
            tx.put(user_path(subject), user.model_dump(mode="json"))
            tx.put("admission_metadata/bootstrap", {"owner_subject": subject, "schema_version": 1})
            self._audit(tx, subject, "owner_bootstrapped", user_key(subject))

        self.store.transact(operation)

    def access(self, identity: Identity) -> AccessView:
        def operation(tx: Transaction) -> AccessView:
            user = read_user(tx, identity.subject)
            workspaces: list[Workspace] = []
            if user is not None and user.active:
                for organization_id in user.organization_ids:
                    org = tx.get(f"admission_organizations/{organization_id}")
                    member = tx.get(member_path(organization_id, identity.subject))
                    if org is not None and member is not None:
                        workspace = Workspace(
                            organization=Organization.model_validate(org),
                            membership=Membership.model_validate(member),
                        )
                        if workspace.organization.active and workspace.membership.active:
                            workspaces.append(workspace)
            admin = bool(user and user.active and user.platform_admin and identity.mfa)
            status = "active" if workspaces or admin else "not_admitted"
            if user is not None and not user.active:
                status = "suspended"
            elif user is not None and user.platform_admin and not identity.mfa:
                status = "mfa_required"
            return AccessView(
                subject=identity.subject,
                email=identity.email,
                platform_admin=admin,
                owner=bool(admin and user and user.owner),
                status=status,
                workspaces=tuple(workspaces),
            )

        return self.store.transact(operation)

    def workspace(self, identity: Identity, organization_id: str) -> Workspace:
        # An admission administrator does not implicitly gain tenant membership.
        for workspace in self.access(identity).workspaces:
            if workspace.organization.organization_id == organization_id:
                return workspace
        raise denied()

    def create_organization(self, identity: Identity, name: str) -> Organization:
        organization = Organization(organization_id=f"org_{uuid4().hex}", name=name)

        def operation(tx: Transaction) -> Organization:
            require_admin(tx, identity)
            tx.put(
                f"admission_organizations/{organization.organization_id}",
                organization.model_dump(mode="json"),
            )
            self._audit(tx, identity.subject, "organization_created", organization.organization_id)
            return organization

        return self.store.transact(operation)

    def invite(self, identity: Identity, request: InvitationCreate) -> tuple[Invitation, str]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invitation = Invitation(
            invitation_id=f"invite_{uuid4().hex}",
            email=request.email.lower(),
            organization_id=request.organization_id,
            role=request.role,
            invited_by=identity.subject,
            expires_at=self.clock() + timedelta(hours=24),
        )

        def operation(tx: Transaction) -> None:
            require_admin(tx, identity)
            document = tx.get(f"admission_organizations/{request.organization_id}")
            if document is None or not Organization.model_validate(document).active:
                raise denied()
            tx.put(f"admission_invitations/{token_hash}", invitation.model_dump(mode="json"))
            self._audit(tx, identity.subject, "invitation_created", invitation.invitation_id)

        self.store.transact(operation)
        return invitation, token

    def redeem(self, identity: Identity, token: str) -> AccessView:
        path = f"admission_invitations/{hashlib.sha256(token.encode()).hexdigest()}"

        def operation(tx: Transaction) -> None:
            document = tx.get(path)
            if document is None:
                raise denied()
            invitation = Invitation.model_validate(document)
            user = read_user(tx, identity.subject)
            inviter = read_user(tx, invitation.invited_by)
            organization = tx.get(f"admission_organizations/{invitation.organization_id}")
            existing = tx.get(member_path(invitation.organization_id, identity.subject))
            if (
                invitation.email != identity.email.lower()
                or invitation.expires_at <= self.clock()
                or invitation.redeemed_by is not None
                or inviter is None
                or not inviter.active
                or not inviter.platform_admin
                or organization is None
                or not Organization.model_validate(organization).active
                or (user is not None and not user.active)
                or existing is not None
            ):
                raise denied()
            user = user or User(subject=identity.subject)
            # An invitation cannot silently reactivate or change an existing membership.
            updated = User.model_validate(
                {
                    **user.model_dump(),
                    "organization_ids": (*user.organization_ids, invitation.organization_id),
                    "version": user.version + 1,
                }
            )
            membership = Membership(
                subject=identity.subject,
                organization_id=invitation.organization_id,
                role=invitation.role,
            )
            tx.put(user_path(identity.subject), updated.model_dump(mode="json"))
            tx.put(
                member_path(invitation.organization_id, identity.subject),
                membership.model_dump(mode="json"),
            )
            tx.put(
                path,
                invitation.model_copy(update={"redeemed_by": identity.subject}).model_dump(
                    mode="json"
                ),
            )
            self._audit(tx, identity.subject, "invitation_redeemed", invitation.invitation_id)

        self.store.transact(operation)
        return self.access(identity)

    def set_status(
        self, identity: Identity, kind: str, identifier: str, request: StatusUpdate
    ) -> None:
        if kind not in {"organizations", "users"}:
            raise denied()
        path = f"admission_{kind}/{identifier}"

        def operation(tx: Transaction) -> None:
            require_admin(tx, identity)
            document = tx.get(path)
            if document is None:
                raise denied()
            if kind == "users":
                target = User.model_validate(document)
                if target.owner or target.subject == identity.subject:
                    raise denied()
            if document["version"] != request.expected_version:
                raise ControlApiError(
                    "version_conflict", "Refresh this record before updating.", 409
                )
            tx.put(
                path,
                {**document, "active": request.active, "version": request.expected_version + 1},
            )
            self._audit(
                tx,
                identity.subject,
                "access_activated" if request.active else "access_suspended",
                path,
            )

        self.store.transact(operation)

    def list_records(self, identity: Identity, kind: str, *, after: str = "") -> list[Document]:
        if kind not in {"organizations", "users", "audit"}:
            raise denied()
        self.store.transact(lambda tx: require_admin(tx, identity))
        return self.store.list(f"admission_{kind}", after=after)

    def set_administrator(self, identity: Identity, identifier: str, request: StatusUpdate) -> None:
        """Only the bootstrapped owner can appoint/revoke admission administrators."""

        def operation(tx: Transaction) -> None:
            actor = require_admin(tx, identity)
            if not actor.owner:
                raise denied()
            path = f"admission_users/{identifier}"
            document = tx.get(path)
            if document is None:
                raise denied()
            target = User.model_validate(document)
            if target.owner or not target.active:
                raise denied()
            if target.version != request.expected_version:
                raise ControlApiError(
                    "version_conflict", "Refresh this record before updating.", 409
                )
            tx.put(
                path,
                target.model_copy(
                    update={
                        "platform_admin": request.active,
                        "version": target.version + 1,
                    }
                ).model_dump(mode="json"),
            )
            self._audit(
                tx,
                identity.subject,
                "administrator_appointed" if request.active else "administrator_revoked",
                identifier,
            )

        self.store.transact(operation)

    def record_rejection(self, actor: str, reason: str) -> None:
        # Deliberately exclude the request URL/body, token, email and arbitrary error message.
        self.store.transact(lambda tx: self._audit(tx, actor, "access_rejected", reason))
