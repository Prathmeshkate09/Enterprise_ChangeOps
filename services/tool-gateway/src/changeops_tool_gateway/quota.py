"""Bounded per-tenant and per-tool concurrency enforcement."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio

from changeops_tool_gateway.errors import RateLimitedError


class ToolQuotaManager:
    def __init__(self, *, maximum_concurrent_per_tool: int = 4) -> None:
        if maximum_concurrent_per_tool < 1:
            raise ValueError("tool quota must be positive")
        self._maximum = maximum_concurrent_per_tool
        self._active: dict[tuple[str, str], int] = defaultdict(int)
        self._lock = anyio.Lock()

    @asynccontextmanager
    async def acquire(self, tenant_id: str, tool_name: str) -> AsyncIterator[None]:
        key = (tenant_id, tool_name)
        async with self._lock:
            if self._active[key] >= self._maximum:
                raise RateLimitedError
            self._active[key] += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active[key] -= 1
                if self._active[key] == 0:
                    del self._active[key]
