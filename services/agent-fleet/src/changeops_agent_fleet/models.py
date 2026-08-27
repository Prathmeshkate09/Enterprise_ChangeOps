"""Deterministic model fake and invocation tracing for ADK tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import BaseModel, PrivateAttr


class InvocationTracker:
    """Records bounded agent calls and observed concurrency."""

    def __init__(self) -> None:
        self.started: dict[str, datetime] = {}
        self.completed: dict[str, datetime] = {}
        self.calls: dict[str, int] = {}
        self.current = 0
        self.max_parallel = 0
        self._lock = asyncio.Lock()

    async def enter(self, agent_id: str) -> None:
        async with self._lock:
            self.started[agent_id] = datetime.now(UTC)
            self.current += 1
            self.max_parallel = max(self.max_parallel, self.current)

    async def exit(self, agent_id: str) -> None:
        async with self._lock:
            self.completed[agent_id] = datetime.now(UTC)
            self.current -= 1

    def record_model_call(self, agent_id: str) -> None:
        self.calls[agent_id] = self.calls.get(agent_id, 0) + 1


class DeterministicModel(BaseLlm):
    """ADK-compatible model whose typed response is derived from test evidence."""

    _agent_id: str = PrivateAttr()
    _responder: Callable[[], BaseModel] = PrivateAttr()
    _tracker: InvocationTracker = PrivateAttr()
    _delay_seconds: float = PrivateAttr()

    def __init__(
        self,
        *,
        agent_id: str,
        responder: Callable[[], BaseModel],
        tracker: InvocationTracker,
        delay_seconds: float = 0.02,
    ) -> None:
        super().__init__(model=f"deterministic-fake/{agent_id}")
        self._agent_id = agent_id
        self._responder = responder
        self._tracker = tracker
        self._delay_seconds = delay_seconds

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del llm_request, stream
        self._tracker.record_model_call(self._agent_id)
        await asyncio.sleep(self._delay_seconds)
        output = self._responder()
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=output.model_dump_json())],
            ),
            turn_complete=True,
        )


def model_name(model: str | BaseLlm) -> str:
    return model if isinstance(model, str) else model.model


def output_from_state(value: Any, output_type: type[BaseModel]) -> BaseModel:
    """Validate ADK state regardless of whether it stored JSON text or a mapping."""

    if isinstance(value, str):
        return output_type.model_validate_json(value)
    return output_type.model_validate(value)
