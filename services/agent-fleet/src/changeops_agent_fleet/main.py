"""ASGI entry point for the agent fleet."""

from changeops_agent_fleet.app import create_app

app = create_app()
