"""ASGI entry point for the Enterprise ChangeOps Control API."""

from control_api.app import create_app

app = create_app()
