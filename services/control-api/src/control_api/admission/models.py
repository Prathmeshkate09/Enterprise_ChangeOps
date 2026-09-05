"""Versioned admission records and strict request/response contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Role(StrEnum):
    ORGANIZATION_ADMIN = "organization_admin"
    REQUESTER = "requester"
    APPROVER = "approver"
    AUDITOR = "auditor"


class Identity(Model):
    subject: Annotated[str, Field(min_length=1, max_length=128)]
    email: Email
    mfa: bool = False


class User(Model):
    subject: str
    active: bool = True
    platform_admin: bool = False
    owner: bool = False
    organization_ids: tuple[Identifier, ...] = Field(default=(), max_length=50)
    version: int = Field(default=1, ge=1)


class Organization(Model):
    organization_id: Identifier
    name: Annotated[str, Field(min_length=2, max_length=120)]
    active: bool = True
    version: int = Field(default=1, ge=1)


class Membership(Model):
    subject: str
    organization_id: Identifier
    role: Role
    active: bool = True
    version: int = Field(default=1, ge=1)


class Invitation(Model):
    invitation_id: Identifier
    email: Email
    organization_id: Identifier
    role: Role
    invited_by: str
    expires_at: AwareDatetime
    redeemed_by: str | None = None


class OrganizationCreate(Model):
    name: Annotated[str, Field(min_length=2, max_length=120)]


class InvitationCreate(Model):
    email: Email
    organization_id: Identifier
    role: Role


class InvitationRedeem(Model):
    token: Annotated[str, Field(min_length=40, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class StatusUpdate(Model):
    active: bool
    expected_version: int = Field(ge=1)


class SessionCreate(Model):
    id_token: Annotated[str, Field(min_length=1, max_length=16384)]


class Workspace(Model):
    organization: Organization
    membership: Membership


class AccessView(Model):
    subject: str
    email: str
    platform_admin: bool
    owner: bool
    status: str
    workspaces: tuple[Workspace, ...]


class AdmissionAudit(Model):
    event_id: Identifier
    actor: str
    action: str
    resource_id: str
    occurred_at: AwareDatetime
