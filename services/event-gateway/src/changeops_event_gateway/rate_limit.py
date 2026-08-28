"""Process-local tenant ingestion guard; managed quotas replace it at the edge."""

from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import RLock

from changeops_event_gateway.errors import EventRateLimitedError


class TenantEventRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = RLock()

    def acquire(self, tenant_id: str, now: datetime) -> None:
        cutoff = now - timedelta(minutes=1)
        with self._lock:
            events = self._events[tenant_id]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                raise EventRateLimitedError
            events.append(now)
