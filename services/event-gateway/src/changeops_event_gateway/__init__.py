"""Enterprise ChangeOps event ingestion boundary."""

from changeops_event_gateway.app import create_app

__all__ = ["create_app"]
