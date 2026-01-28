"""Metrics tracking for backpressure middleware"""

import asyncio
from dataclasses import dataclass


@dataclass
class BackpressureMetrics:
    """
    Metrics for backpressure middleware.

    Tracks current state and total counters for monitoring.
    Thread-safe through internal lock.
    """

    active: int = 0
    """Current number of actively executing requests"""

    queued: int = 0
    """Current number of requests waiting in queue"""

    total_rejected: int = 0
    """Total number of rejected requests (all reasons)"""

    rejected_concurrency_limit: int = 0
    """Number of requests rejected due to concurrency limit (no queue)"""

    rejected_queue_full: int = 0
    """Number of requests rejected due to full queue"""

    rejected_queue_timeout: int = 0
    """Number of requests rejected due to queue timeout"""


class MetricsTracker:
    """
    Thread-safe metrics tracker for backpressure middleware.

    Provides atomic operations for updating counters.
    """

    def __init__(self):
        self._active = 0
        self._queued = 0
        self._total_rejected = 0
        self._rejected_concurrency_limit = 0
        self._rejected_queue_full = 0
        self._rejected_queue_timeout = 0
        self._lock = asyncio.Lock()

    async def increment_active(self) -> None:
        """Increment active counter."""
        async with self._lock:
            self._active += 1

    async def decrement_active(self) -> None:
        """Decrement active counter."""
        async with self._lock:
            self._active -= 1

    async def increment_queued(self) -> None:
        """Increment queued counter."""
        async with self._lock:
            self._queued += 1

    async def decrement_queued(self) -> None:
        """Decrement queued counter."""
        async with self._lock:
            self._queued -= 1

    async def increment_rejected(self, reason: str) -> None:
        """
        Increment rejection counters.

        Args:
            reason: Rejection reason ('concurrency_limit', 'queue_full', 'queue_timeout')
        """
        async with self._lock:
            self._total_rejected += 1
            if reason == "concurrency_limit":
                self._rejected_concurrency_limit += 1
            elif reason == "queue_full":
                self._rejected_queue_full += 1
            elif reason == "queue_timeout":
                self._rejected_queue_timeout += 1

    async def get_metrics(self) -> BackpressureMetrics:
        """
        Get current metrics snapshot.

        Returns:
            BackpressureMetrics with current values
        """
        async with self._lock:
            return BackpressureMetrics(
                active=self._active,
                queued=self._queued,
                total_rejected=self._total_rejected,
                rejected_concurrency_limit=self._rejected_concurrency_limit,
                rejected_queue_full=self._rejected_queue_full,
                rejected_queue_timeout=self._rejected_queue_timeout,
            )
