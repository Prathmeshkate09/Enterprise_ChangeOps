"""Operational repository selection from validated settings."""

from changeops_core import PersistenceBackend, Settings
from changeops_persistence import (
    ChangeStateRepository,
    FirestoreChangeStateRepository,
    InMemoryChangeStateRepository,
)


def build_repository(settings: Settings) -> ChangeStateRepository:
    if settings.persistence_backend is PersistenceBackend.MEMORY:
        return InMemoryChangeStateRepository()
    if settings.google_cloud_project is None:
        raise RuntimeError("Validated Firestore settings are missing GOOGLE_CLOUD_PROJECT.")
    return FirestoreChangeStateRepository.from_project(
        settings.google_cloud_project,
        settings.firestore_database,
    )
