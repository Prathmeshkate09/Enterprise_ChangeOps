"""Google Pub/Sub publisher adapter with emulator support through standard env vars."""

from __future__ import annotations

from typing import Protocol

from changeops_contracts import ChangeEvent
from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1  # type: ignore[attr-defined]


class EventPublisher(Protocol):
    def ensure_ready(self) -> None: ...

    def check_ready(self) -> None: ...

    def publish(self, event: ChangeEvent, change_id: str) -> str: ...


class PubSubEventPublisher:
    def __init__(self, project: str, topic_id: str) -> None:
        self._client = pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project, topic_id)

    def ensure_ready(self) -> None:
        try:
            self._client.create_topic(request={"name": self._topic_path})
        except AlreadyExists:
            pass

    def check_ready(self) -> None:
        self._client.get_topic(request={"topic": self._topic_path})

    def publish(self, event: ChangeEvent, change_id: str) -> str:
        future = self._client.publish(
            self._topic_path,
            event.model_dump_json().encode("utf-8"),
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            change_id=change_id,
            trace_id=event.trace_id,
        )
        return str(future.result(timeout=10))
