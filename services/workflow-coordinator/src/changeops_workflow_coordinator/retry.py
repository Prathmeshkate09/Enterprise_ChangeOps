"""Bounded exponential retry policy with injected jitter."""

from __future__ import annotations

from collections.abc import Callable


class RetryPolicy:
    def __init__(
        self,
        *,
        maximum_attempts: int,
        base_delay_seconds: float,
        maximum_delay_seconds: float = 10.0,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if base_delay_seconds <= 0 or maximum_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        self.maximum_attempts = maximum_attempts
        self.base_delay_seconds = base_delay_seconds
        self.maximum_delay_seconds = maximum_delay_seconds
        self._jitter = jitter or (lambda: 0.5)

    def should_retry(self, *, transient: bool, attempt: int) -> bool:
        return transient and attempt < self.maximum_attempts

    def delay(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        exponential = min(
            self.maximum_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt - 1)),
        )
        jitter_factor = 0.8 + (max(0.0, min(1.0, self._jitter())) * 0.4)
        return float(exponential * jitter_factor)
