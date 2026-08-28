"""Pub/Sub pull subscriber with explicit permanent-failure dead lettering."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Protocol

from changeops_contracts import ChangeEvent
from changeops_core import get_logger
from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1  # type: ignore[attr-defined]
from pydantic import ValidationError

from changeops_workflow_coordinator.engine import WorkflowEngine
from changeops_workflow_coordinator.errors import WorkflowPermanentError, WorkflowTransientError
from changeops_workflow_coordinator.models import WorkflowRuntimeStatus


class WorkflowSubscriber(Protocol):
    def ensure_ready(self) -> None: ...

    def check_ready(self) -> None: ...

    def start(self, loop: asyncio.AbstractEventLoop) -> None: ...

    def stop(self) -> None: ...


class PubSubMessage(Protocol):
    data: bytes

    def ack(self) -> None: ...

    def nack(self) -> None: ...


class PubSubWorkflowSubscriber:
    def __init__(
        self,
        *,
        project: str,
        topic_id: str,
        subscription_id: str,
        dead_letter_topic_id: str,
        dead_letter_subscription_id: str,
        engine: WorkflowEngine,
    ) -> None:
        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()
        self._topic = self._publisher.topic_path(project, topic_id)
        self._subscription = self._subscriber.subscription_path(project, subscription_id)
        self._dead_letter_topic = self._publisher.topic_path(project, dead_letter_topic_id)
        self._dead_letter_subscription = self._subscriber.subscription_path(
            project, dead_letter_subscription_id
        )
        self._engine = engine
        self._logger = get_logger("workflow-subscriber")
        self._streaming_future: object | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def ensure_ready(self) -> None:
        for topic in (self._topic, self._dead_letter_topic):
            try:
                self._publisher.create_topic(request={"name": topic})
            except AlreadyExists:
                pass
        try:
            self._subscriber.create_subscription(
                request={
                    "name": self._subscription,
                    "topic": self._topic,
                    "ack_deadline_seconds": 60,
                    "retry_policy": pubsub_v1.types.RetryPolicy(
                        minimum_backoff={"seconds": 1},
                        maximum_backoff={"seconds": 10},
                    ),
                    "dead_letter_policy": pubsub_v1.types.DeadLetterPolicy(
                        dead_letter_topic=self._dead_letter_topic,
                        max_delivery_attempts=5,
                    ),
                }
            )
        except AlreadyExists:
            pass
        try:
            self._subscriber.create_subscription(
                request={
                    "name": self._dead_letter_subscription,
                    "topic": self._dead_letter_topic,
                    "ack_deadline_seconds": 30,
                }
            )
        except AlreadyExists:
            pass

    def check_ready(self) -> None:
        self._subscriber.get_subscription(request={"subscription": self._subscription})

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._streaming_future is not None:
            return
        self._loop = loop
        self._streaming_future = self._subscriber.subscribe(
            self._subscription,
            callback=self._handle_message,
            flow_control=pubsub_v1.types.FlowControl(max_messages=10),
        )

    def stop(self) -> None:
        future = self._streaming_future
        self._streaming_future = None
        if future is None:
            return
        future.cancel()  # type: ignore[attr-defined]
        try:
            future.result(timeout=10)  # type: ignore[attr-defined]
        except Exception as error:
            self._logger.warning("pubsub_subscriber_stop_failed", error=str(error))

    def _handle_message(self, message: PubSubMessage) -> None:
        try:
            event = ChangeEvent.model_validate_json(message.data)
        except ValidationError as error:
            self._logger.error("pubsub_invalid_event", error=str(error))
            self._publish_dead_letter(message.data, "INVALID_EVENT_SCHEMA")
            message.ack()
            return
        if self._loop is None:
            message.nack()
            return
        future = asyncio.run_coroutine_threadsafe(self._engine.process_event(event), self._loop)
        try:
            record = future.result(timeout=300)
        except WorkflowTransientError as error:
            self._logger.warning("workflow_transient_failure", error_code=error.code)
            message.nack()
            return
        except WorkflowPermanentError as error:
            self._logger.error("workflow_permanent_failure", error_code=error.code)
            self._publish_dead_letter(message.data, error.code)
            message.ack()
            return
        except FutureTimeoutError:
            self._logger.error("workflow_processing_timeout")
            future.cancel()
            message.nack()
            return
        except Exception as error:
            self._logger.exception("workflow_processing_failed", error=str(error))
            message.nack()
            return
        if record.status is WorkflowRuntimeStatus.DEAD_LETTERED:
            self._publish_dead_letter(message.data, record.last_error_code or "WORKFLOW_FAILED")
        message.ack()

    def _publish_dead_letter(self, payload: bytes, error_code: str) -> None:
        future = self._publisher.publish(
            self._dead_letter_topic,
            payload,
            error_code=error_code,
            source_subscription=self._subscription,
        )
        future.result(timeout=10)
