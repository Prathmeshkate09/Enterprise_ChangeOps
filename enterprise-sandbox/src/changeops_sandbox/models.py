"""Typed contracts used only by the disclosed synthetic sandbox services."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class SandboxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ApiContract(SandboxModel):
    api: NonEmptyStr
    version: NonEmptyStr
    identifier_field: NonEmptyStr
    identifier_type: NonEmptyStr
    compatibility: NonEmptyStr
    owner: NonEmptyStr


class DependencyEdge(SandboxModel):
    source: NonEmptyStr
    target: NonEmptyStr
    managed: bool


class CatalogSeed(SandboxModel):
    active_version: NonEmptyStr
    contracts: tuple[ApiContract, ...] = Field(min_length=1)
    dependencies: tuple[DependencyEdge, ...] = Field(min_length=1)
    artifact_refs: tuple[NonEmptyStr, ...]


class SystemConfiguration(SandboxModel):
    system_id: NonEmptyStr


class CrmConfiguration(SystemConfiguration):
    source_field: NonEmptyStr
    destination_field: NonEmptyStr
    schema_version: int = Field(ge=1)
    status: NonEmptyStr


class AnalyticsConfiguration(SystemConfiguration):
    source_field: NonEmptyStr
    output_field: NonEmptyStr
    dependent_dashboards: tuple[NonEmptyStr, ...]
    baseline_row_count: int = Field(gt=0)
    status: NonEmptyStr


class AnalyticsDataProfile(SandboxModel):
    system_id: NonEmptyStr
    observed_row_count: int = Field(gt=0)
    identifier_null_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_null_count(self) -> Self:
        if self.identifier_null_count > self.observed_row_count:
            raise ValueError("identifier_null_count cannot exceed observed_row_count")
        return self


class SupportConfiguration(SystemConfiguration):
    lookup_field: NonEmptyStr
    dependent_forms: tuple[NonEmptyStr, ...]
    status: NonEmptyStr


class SnapshotRecord(SandboxModel):
    snapshot_id: NonEmptyStr
    tenant_id: NonEmptyStr
    system_id: NonEmptyStr
    configuration: dict[str, JsonValue]
    configuration_hash: Sha256Digest
    created_at: AwareDatetime


class FieldPatchRequest(SandboxModel):
    old_field: NonEmptyStr
    new_field: NonEmptyStr
    idempotency_key: NonEmptyStr
    change_id: NonEmptyStr
    plan_hash: Sha256Digest


class PatchPreview(SandboxModel):
    system_id: NonEmptyStr
    field_name: NonEmptyStr
    before: NonEmptyStr
    after: NonEmptyStr
    would_change: bool


class PatchResult(SandboxModel):
    system_id: NonEmptyStr
    field_name: NonEmptyStr
    before: NonEmptyStr
    after: NonEmptyStr
    idempotency_key: NonEmptyStr
    configuration_hash: Sha256Digest
    replayed: bool


class RestoreResult(SandboxModel):
    system_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    configuration_hash: Sha256Digest
    restored: bool


class VerificationRequest(SandboxModel):
    expected_field: NonEmptyStr


class VerificationCheck(SandboxModel):
    name: NonEmptyStr
    passed: bool
    detail: NonEmptyStr


class VerificationResult(SandboxModel):
    system_id: NonEmptyStr
    passed: bool
    checks: tuple[VerificationCheck, ...] = Field(min_length=1)


class FieldUsageResult(SandboxModel):
    field: NonEmptyStr
    resources: tuple[NonEmptyStr, ...]


class DataQualityResult(VerificationResult):
    baseline_row_count: int = Field(gt=0)
    observed_row_count: int = Field(gt=0)
    null_rate: float = Field(ge=0.0, le=1.0)


class TransientFailureRequest(SandboxModel):
    count: int = Field(default=1, ge=1, le=3)


class TransientFailureState(SandboxModel):
    remaining_failures: int = Field(ge=0)


class VerificationFailureRequest(SandboxModel):
    count: int = Field(default=1, ge=1, le=3)


class VerificationFailureState(SandboxModel):
    remaining_failures: int = Field(ge=0)


class CatalogActivationRequest(SandboxModel):
    version: NonEmptyStr
    idempotency_key: NonEmptyStr
    change_id: NonEmptyStr
    plan_hash: Sha256Digest


class CatalogActivationResult(SandboxModel):
    active_contract: ApiContract
    idempotency_key: NonEmptyStr
    replayed: bool


class ResetResult(SandboxModel):
    tenant_id: NonEmptyStr
    reset: bool
