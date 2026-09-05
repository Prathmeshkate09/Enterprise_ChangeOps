"""Explicit one-time owner admission. Does not create an Identity Platform account."""

from __future__ import annotations

import argparse
import os

import firebase_admin  # type: ignore[import-untyped]  # SDK does not publish py.typed.
from changeops_core import get_settings
from control_api.admission.service import AdmissionService
from control_api.admission.store import FirestoreStore
from firebase_admin import auth
from google.cloud import firestore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, help="Existing verified Identity Platform UID")
    args = parser.parse_args()
    if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") or os.environ.get("FIRESTORE_EMULATOR_HOST"):
        raise SystemExit("Managed owner bootstrap must not mix emulator and cloud resources.")
    settings = get_settings()
    if not settings.enterprise_access_enabled:
        raise SystemExit("Explicit enterprise access configuration is required.")
    app = firebase_admin.initialize_app(options={"projectId": settings.identity_platform_project})
    user = auth.get_user(args.subject, app=app)
    if user.disabled or not user.email_verified or not user.email:
        raise SystemExit("Owner must be an existing, enabled, verified provider account.")
    service = AdmissionService(
        FirestoreStore(
            firestore.Client(
                project=settings.google_cloud_project,
                database=settings.firestore_database,
            )
        )
    )
    service.bootstrap_owner(user.uid)
    print("Owner initialized with atomic audit evidence. MFA is required for administrator access.")


if __name__ == "__main__":
    main()
