"""Strict event inbox and HTTP contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from changeops_contracts import ChangeEvent
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class EventGatewayModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class InboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    DEAD_LETTERED = "DEAD_LETTERED"


class EventInboxRecord(EventGatewayModel):
    event_key: NonEmptyStr
    tenant_id: NonEmptyStr
    event_id: NonEmptyStr
    source_type: NonEmptyStr
    change_id: NonEmptyStr
    input_hash: Sha256Digest
    event: ChangeEvent
    status: InboxStatus
    publish_attempts: int = Field(ge=0)
    processing_attempts: int = Field(ge=0)
    pubsub_message_id: NonEmptyStr | None = None
    last_error_code: NonEmptyStr | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int = Field(ge=1)


class InboxAcceptance(EventGatewayModel):
    record: EventInboxRecord
    replayed: bool


class EventAcceptedResponse(EventGatewayModel):
    event_id: NonEmptyStr
    change_id: NonEmptyStr
    status: InboxStatus
    status_url: NonEmptyStr
    replayed: bool


class HealthResponse(EventGatewayModel):
    service: str
    status: str
