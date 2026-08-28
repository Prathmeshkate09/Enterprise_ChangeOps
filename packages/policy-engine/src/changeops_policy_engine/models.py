"""Validated identity and tool-registry policy inputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from changeops_contracts import ChangeEnvironment, RiskLevel, UserRole
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]


class IdentityKind(StrEnum):
    AGENT = "agent"
    SERVICE = "service"
    USER = "user"


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VerifiedIdentity(PolicyModel):
    subject: NonEmptyStr
    tenant_id: NonEmptyStr
    kind: IdentityKind
    roles: tuple[UserRole, ...] = ()
    audience: NonEmptyStr
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_claims(self) -> VerifiedIdentity:
        if self.expires_at <= self.issued_at:
            raise ValueError("identity expiration must be after issuance")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("identity roles must be unique")
        if self.kind is not IdentityKind.USER and self.roles:
            raise ValueError("only user identities may carry user roles")
        return self


class ToolRegistration(PolicyModel):
    tool_name: NonEmptyStr
    owning_agent_id: NonEmptyStr
    action: NonEmptyStr
    resource_pattern: NonEmptyStr
    risk_level: RiskLevel
    mutating: bool
    allowed_environments: tuple[ChangeEnvironment, ...] = Field(min_length=1)
    policy_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, le=60)

    @model_validator(mode="after")
    def validate_registration(self) -> ToolRegistration:
        if "*" in self.tool_name or self.tool_name in {"execute_sql", "run_shell", "fetch_url"}:
            raise ValueError("tool names must be exact and bounded")
        if self.mutating and ChangeEnvironment.SANDBOX not in self.allowed_environments:
            raise ValueError("mutating demo tools must be restricted to the sandbox environment")
        if len(self.policy_ids) != len(set(self.policy_ids)):
            raise ValueError("policy_ids values must be unique")
        return self
