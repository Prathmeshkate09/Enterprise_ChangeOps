"""Control API request, response, and disclosed demo-seed models."""

from typing import Annotated

from changeops_contracts import (
    AuditEvent,
    ChangeEnvironment,
    ChangeRecord,
    ChangeSource,
    RiskLevel,
)
from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ServiceResponse(ApiModel):
    service: str
    status: str
    environment: str
    persistence_backend: str
    production_writes_enabled: bool


class HealthResponse(ApiModel):
    service: str
    status: str


class ChangeListResponse(ApiModel):
    items: tuple[ChangeRecord, ...]
    count: int = Field(ge=0)


class AuditListResponse(ApiModel):
    items: tuple[AuditEvent, ...]
    count: int = Field(ge=0)


class TransitionRequest(ApiModel):
    expected_version: int = Field(ge=1)
    trace_id: Identifier


class DemoChangeSeed(ApiModel):
    change_id: Identifier
    event_id: Identifier
    change_type: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=2048)
    source: ChangeSource
    environment: ChangeEnvironment
    risk_level: RiskLevel
    created_by: Identifier
    trace_id: Identifier
