"""ASGI entrypoint."""

from changeops_tool_gateway.app import create_app

app = create_app()
