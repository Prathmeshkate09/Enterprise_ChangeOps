"""Thread-safe, tenant-scoped synthetic state with snapshot compensation."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import cast
from uuid import uuid4

from changeops_contracts import sha256_digest
from pydantic import JsonValue

from changeops_sandbox.errors import (
    ContractVersionNotFoundError,
    PatchConflictError,
    SnapshotNotFoundError,
    TenantScopeError,
    TransientSandboxError,
)
from changeops_sandbox.models import (
    ApiContract,
    CatalogActivationRequest,
    CatalogActivationResult,
    CatalogSeed,
    DependencyEdge,
    FieldPatchRequest,
    PatchPreview,
    PatchResult,
    ResetResult,
    RestoreResult,
    SnapshotRecord,
    SystemConfiguration,
    TransientFailureState,
    VerificationFailureState,
)


def _new_snapshot_id() -> str:
    return f"snapshot_{uuid4().hex}"


class ConfigurationStore[ConfigModel: SystemConfiguration]:
    def __init__(
        self,
        seed: ConfigModel,
        model_type: type[ConfigModel],
        *,
        field_name: str,
    ) -> None:
        if not hasattr(seed, field_name):
            raise ValueError(f"Seed model has no mutable field {field_name!r}.")
        self._seed = seed
        self._model_type = model_type
        self._field_name = field_name
        self._lock = RLock()
        self._configurations: dict[str, ConfigModel] = {}
        self._snapshots: dict[tuple[str, str], SnapshotRecord] = {}
        self._snapshot_tenants: dict[str, str] = {}
        self._executions: dict[tuple[str, str], PatchResult] = {}
        self._transient_failures: dict[str, int] = {}
        self._verification_failures: dict[str, int] = {}

    def get(self, tenant_id: str) -> ConfigModel:
        with self._lock:
            return self._get_unlocked(tenant_id)

    def snapshot(self, tenant_id: str) -> SnapshotRecord:
        with self._lock:
            configuration = self._get_unlocked(tenant_id)
            document = cast(dict[str, JsonValue], configuration.model_dump(mode="json"))
            snapshot = SnapshotRecord(
                snapshot_id=_new_snapshot_id(),
                tenant_id=tenant_id,
                system_id=configuration.system_id,
                configuration=document,
                configuration_hash=sha256_digest(document),
                created_at=datetime.now(UTC),
            )
            self._snapshots[(tenant_id, snapshot.snapshot_id)] = snapshot
            self._snapshot_tenants[snapshot.snapshot_id] = tenant_id
            return snapshot

    def dry_run(self, tenant_id: str, request: FieldPatchRequest) -> PatchPreview:
        with self._lock:
            configuration = self._get_unlocked(tenant_id)
            current = str(getattr(configuration, self._field_name))
            if current != request.old_field:
                raise PatchConflictError(request.old_field, current)
            return PatchPreview(
                system_id=configuration.system_id,
                field_name=self._field_name,
                before=current,
                after=request.new_field,
                would_change=current != request.new_field,
            )

    def apply(self, tenant_id: str, request: FieldPatchRequest) -> PatchResult:
        key = (tenant_id, request.idempotency_key)
        with self._lock:
            prior = self._executions.get(key)
            if prior is not None:
                return PatchResult.model_validate(
                    {**prior.model_dump(mode="python"), "replayed": True}
                )
            remaining_failures = self._transient_failures.get(tenant_id, 0)
            if remaining_failures:
                self._transient_failures[tenant_id] = remaining_failures - 1
                raise TransientSandboxError

            configuration = self._get_unlocked(tenant_id)
            current = str(getattr(configuration, self._field_name))
            if current != request.old_field:
                raise PatchConflictError(request.old_field, current)
            document = configuration.model_dump(mode="python")
            document[self._field_name] = request.new_field
            if "schema_version" in document:
                document["schema_version"] = int(document["schema_version"]) + 1
            updated = self._model_type.model_validate(document)
            self._configurations[tenant_id] = updated
            updated_json = updated.model_dump(mode="json")
            result = PatchResult(
                system_id=updated.system_id,
                field_name=self._field_name,
                before=current,
                after=request.new_field,
                idempotency_key=request.idempotency_key,
                configuration_hash=sha256_digest(updated_json),
                replayed=False,
            )
            self._executions[key] = result
            return result

    def restore(self, tenant_id: str, snapshot_id: str) -> RestoreResult:
        with self._lock:
            snapshot = self._snapshots.get((tenant_id, snapshot_id))
            if snapshot is None:
                if snapshot_id in self._snapshot_tenants:
                    raise TenantScopeError
                raise SnapshotNotFoundError(snapshot_id)
            restored = self._model_type.model_validate(snapshot.configuration)
            self._configurations[tenant_id] = restored
            return RestoreResult(
                system_id=snapshot.system_id,
                snapshot_id=snapshot_id,
                configuration_hash=snapshot.configuration_hash,
                restored=True,
            )

    def inject_transient_failures(
        self,
        tenant_id: str,
        count: int,
    ) -> TransientFailureState:
        with self._lock:
            self._transient_failures[tenant_id] = count
            return TransientFailureState(remaining_failures=count)

    def inject_verification_failures(
        self,
        tenant_id: str,
        count: int,
    ) -> VerificationFailureState:
        with self._lock:
            self._verification_failures[tenant_id] = count
            return VerificationFailureState(remaining_failures=count)

    def consume_verification_failure(self, tenant_id: str) -> bool:
        with self._lock:
            remaining = self._verification_failures.get(tenant_id, 0)
            if remaining == 0:
                return False
            if remaining == 1:
                self._verification_failures.pop(tenant_id, None)
            else:
                self._verification_failures[tenant_id] = remaining - 1
            return True

    def reset(self, tenant_id: str) -> ResetResult:
        with self._lock:
            self._configurations[tenant_id] = self._copy_seed()
            self._transient_failures.pop(tenant_id, None)
            self._verification_failures.pop(tenant_id, None)
            self._executions = {
                key: value for key, value in self._executions.items() if key[0] != tenant_id
            }
            tenant_snapshot_ids = [
                snapshot_id for (owner, snapshot_id) in self._snapshots if owner == tenant_id
            ]
            for snapshot_id in tenant_snapshot_ids:
                self._snapshots.pop((tenant_id, snapshot_id))
                self._snapshot_tenants.pop(snapshot_id, None)
            return ResetResult(tenant_id=tenant_id, reset=True)

    def _get_unlocked(self, tenant_id: str) -> ConfigModel:
        configuration = self._configurations.get(tenant_id)
        if configuration is None:
            configuration = self._copy_seed()
            self._configurations[tenant_id] = configuration
        return configuration

    def _copy_seed(self) -> ConfigModel:
        return self._model_type.model_validate(self._seed.model_dump(mode="python"))


class CatalogStore:
    def __init__(self, seed: CatalogSeed) -> None:
        self._seed = seed
        self._lock = RLock()
        self._active_versions: dict[str, str] = {}
        self._snapshots: dict[tuple[str, str], SnapshotRecord] = {}
        self._snapshot_tenants: dict[str, str] = {}
        self._executions: dict[tuple[str, str], CatalogActivationResult] = {}

    def active_contract(self, tenant_id: str) -> ApiContract:
        with self._lock:
            version = self._active_versions.get(tenant_id, self._seed.active_version)
            return self._contract_for_version(version)

    def contract_version(self, version: str) -> ApiContract:
        with self._lock:
            return self._contract_for_version(version)

    def dependencies(self, source: str | None = None) -> tuple[DependencyEdge, ...]:
        with self._lock:
            if source is None:
                return self._seed.dependencies
            return tuple(edge for edge in self._seed.dependencies if edge.source == source)

    def snapshot(self, tenant_id: str) -> SnapshotRecord:
        with self._lock:
            contract = self.active_contract(tenant_id)
            document = cast(dict[str, JsonValue], contract.model_dump(mode="json"))
            snapshot = SnapshotRecord(
                snapshot_id=_new_snapshot_id(),
                tenant_id=tenant_id,
                system_id="customer-api",
                configuration=document,
                configuration_hash=sha256_digest(document),
                created_at=datetime.now(UTC),
            )
            self._snapshots[(tenant_id, snapshot.snapshot_id)] = snapshot
            self._snapshot_tenants[snapshot.snapshot_id] = tenant_id
            return snapshot

    def activate(
        self,
        tenant_id: str,
        request: CatalogActivationRequest,
    ) -> CatalogActivationResult:
        key = (tenant_id, request.idempotency_key)
        with self._lock:
            prior = self._executions.get(key)
            if prior is not None:
                return CatalogActivationResult(
                    active_contract=prior.active_contract,
                    idempotency_key=prior.idempotency_key,
                    replayed=True,
                )
            contract = self._contract_for_version(request.version)
            self._active_versions[tenant_id] = contract.version
            result = CatalogActivationResult(
                active_contract=contract,
                idempotency_key=request.idempotency_key,
                replayed=False,
            )
            self._executions[key] = result
            return result

    def restore(self, tenant_id: str, snapshot_id: str) -> RestoreResult:
        with self._lock:
            snapshot = self._snapshots.get((tenant_id, snapshot_id))
            if snapshot is None:
                if snapshot_id in self._snapshot_tenants:
                    raise TenantScopeError
                raise SnapshotNotFoundError(snapshot_id)
            contract = ApiContract.model_validate(snapshot.configuration)
            self._active_versions[tenant_id] = contract.version
            return RestoreResult(
                system_id="customer-api",
                snapshot_id=snapshot_id,
                configuration_hash=snapshot.configuration_hash,
                restored=True,
            )

    def reset(self, tenant_id: str) -> ResetResult:
        with self._lock:
            self._active_versions[tenant_id] = self._seed.active_version
            self._executions = {
                key: value for key, value in self._executions.items() if key[0] != tenant_id
            }
            tenant_snapshot_ids = [
                snapshot_id for (owner, snapshot_id) in self._snapshots if owner == tenant_id
            ]
            for snapshot_id in tenant_snapshot_ids:
                self._snapshots.pop((tenant_id, snapshot_id))
                self._snapshot_tenants.pop(snapshot_id, None)
            return ResetResult(tenant_id=tenant_id, reset=True)

    def _contract_for_version(self, version: str) -> ApiContract:
        contract = next(
            (candidate for candidate in self._seed.contracts if candidate.version == version),
            None,
        )
        if contract is None:
            raise ContractVersionNotFoundError(version)
        return contract
