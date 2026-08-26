"""Structured logging with recursive secret and personal-data redaction."""

import logging
import re
import sys
from collections.abc import Mapping, Sequence
from typing import cast

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

type LogValue = str | int | float | bool | None | Mapping[str, LogValue] | Sequence[LogValue]

_SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "authorization",
        "callback_secret",
        "cookie",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive_data(value: LogValue, *, key: str | None = None) -> LogValue:
    """Return a redacted copy of log-safe scalar or nested structured data."""

    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_sensitive_data(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, str):
        without_bearer = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        return _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", without_bearer)
    return value


def redact_event(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor that redacts an event before serialization."""

    redacted = redact_sensitive_data(event_dict)
    if not isinstance(redacted, dict):
        raise TypeError("Structured log event must remain a dictionary after redaction.")
    return redacted


def configure_logging(level: str = "INFO") -> None:
    """Configure JSON logging for services and local development."""

    resolved_level = getattr(logging, level.upper(), None)
    if not isinstance(resolved_level, int):
        raise ValueError(f"Unsupported log level: {level}")

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=resolved_level,
        force=True,
    )
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_event,
        structlog.processors.JSONRenderer(sort_keys=True),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(resolved_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a component-bound structured logger."""

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(component=name))
