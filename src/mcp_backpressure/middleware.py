"""Backpressure middleware for FastMCP servers"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import OverloadError
from .metrics import BackpressureMetrics, MetricsTracker


class BackpressureMiddleware:
    """
    Middleware that limits concurrent request executions with optional queueing.

    Provides two-level limiting:
    1. Semaphore for active execution slots (max_concurrent)
    2. Bounded queue for waiting requests (queue_size)

    When both limits are reached, new requests are rejected with OverloadError.

    Example:
        mcp = FastMCP("MyServer")
        mcp.add_middleware(BackpressureMiddleware(
            max_concurrent=5,
            queue_size=10,
            queue_timeout=30.0
        ))
    """

    def __init__(
        self,
        max_concurrent: int,
        queue_size: int = 0,
        queue_timeout: float = 30.0,
        overload_error_code: int = -32001,
        on_overload: Callable[[OverloadError], None] | None = None,
    ):
        """
        Create a BackpressureMiddleware.

        Args:
            max_concurrent: Maximum number of concurrent request executions
            queue_size: Maximum queue size (0 = no queue, reject immediately)
            queue_timeout: Maximum time to wait in queue (seconds)
            overload_error_code: JSON-RPC error code for overload errors
            on_overload: Optional callback called on each overload

        Raises:
            ValueError: If max_concurrent < 1 or queue_size < 0
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        if queue_size < 0:
            raise ValueError(f"queue_size must be >= 0, got {queue_size}")
        if queue_timeout <= 0:
            raise ValueError(f"queue_timeout must be > 0, got {queue_timeout}")

        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.queue_timeout = queue_timeout
        self.overload_error_code = overload_error_code
        self.on_overload = on_overload

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._metrics = MetricsTracker()
        self._queue_semaphore = asyncio.Semaphore(queue_size) if queue_size > 0 else None

    @property
    def active(self) -> int:
        """Get current number of active requests."""
        return self._metrics._active

    @property
    def queued(self) -> int:
        """Get current number of queued requests."""
        return self._metrics._queued

    def get_metrics(self) -> BackpressureMetrics:
        """
        Get current metrics snapshot (synchronous).

        Note: This is a synchronous method that returns cached counters.
        For fully consistent metrics, use get_metrics_async().

        Returns:
            BackpressureMetrics with current values
        """
        return BackpressureMetrics(
            active=self._metrics._active,
            queued=self._metrics._queued,
            total_rejected=self._metrics._total_rejected,
            rejected_concurrency_limit=self._metrics._rejected_concurrency_limit,
            rejected_queue_full=self._metrics._rejected_queue_full,
            rejected_queue_timeout=self._metrics._rejected_queue_timeout,
        )

    async def get_metrics_async(self) -> BackpressureMetrics:
        """
        Get current metrics snapshot (async, thread-safe).

        Returns:
            BackpressureMetrics with current values
        """
        return await self._metrics.get_metrics()

    async def __call__(
        self,
        request: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """
        Process request with concurrency limiting and queueing.

        Logic:
        - If active < max_concurrent: execute immediately
        - If active == max_concurrent AND queued < queue_size: wait in queue with timeout
        - If queued == queue_size: reject with reason='queue_full'
        - If timeout in queue: reject with reason='queue_timeout'

        Args:
            request: The incoming request
            call_next: Function to call next middleware/handler

        Returns:
            Response from call_next

        Raises:
            OverloadError: If limits are reached or queue timeout occurs
        """
        # Check if we need to queue
        should_queue = False
        queued_successfully = False

        if self._semaphore.locked():
            # Semaphore is full, need to queue or reject
            should_queue = True

            if self.queue_size == 0:
                # No queue configured, reject immediately
                metrics = await self._metrics.get_metrics()
                await self._metrics.increment_rejected("concurrency_limit")
                error = OverloadError(
                    reason="concurrency_limit",
                    active=metrics.active,
                    max_concurrent=self.max_concurrent,
                    queued=metrics.queued,
                    queue_size=self.queue_size,
                    queue_timeout_ms=int(self.queue_timeout * 1000),
                    code=self.overload_error_code,
                )
                if self.on_overload:
                    self.on_overload(error)
                raise error

            # Try to acquire queue slot
            if self._queue_semaphore.locked():
                # Queue is full, reject immediately
                metrics = await self._metrics.get_metrics()
                await self._metrics.increment_rejected("queue_full")
                error = OverloadError(
                    reason="queue_full",
                    active=metrics.active,
                    max_concurrent=self.max_concurrent,
                    queued=metrics.queued,
                    queue_size=self.queue_size,
                    queue_timeout_ms=int(self.queue_timeout * 1000),
                    code=self.overload_error_code,
                )
                if self.on_overload:
                    self.on_overload(error)
                raise error

            # Acquire queue slot
            await self._queue_semaphore.acquire()
            await self._metrics.increment_queued()
            queued_successfully = True

        # Now try to acquire execution semaphore
        start_time = time.monotonic()

        try:
            if should_queue and queued_successfully:
                # We're queued, wait for semaphore with timeout
                remaining_timeout = self.queue_timeout - (time.monotonic() - start_time)
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError()

                await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=remaining_timeout
                )

                # Got semaphore, no longer queued
                await self._metrics.decrement_queued()
                self._queue_semaphore.release()
                queued_successfully = False

                # Execute
                await self._metrics.increment_active()
                try:
                    return await call_next(request)
                finally:
                    await self._metrics.decrement_active()
                    self._semaphore.release()

            else:
                # Fast path: execute immediately
                async with self._semaphore:
                    await self._metrics.increment_active()
                    try:
                        return await call_next(request)
                    finally:
                        await self._metrics.decrement_active()

        except asyncio.TimeoutError:
            # Queue timeout expired
            if queued_successfully:
                await self._metrics.decrement_queued()
                self._queue_semaphore.release()

            metrics = await self._metrics.get_metrics()
            await self._metrics.increment_rejected("queue_timeout")
            error = OverloadError(
                reason="queue_timeout",
                active=metrics.active,
                max_concurrent=self.max_concurrent,
                queued=metrics.queued,
                queue_size=self.queue_size,
                queue_timeout_ms=int(self.queue_timeout * 1000),
                code=self.overload_error_code,
            )
            if self.on_overload:
                self.on_overload(error)
            raise error from None

        except asyncio.CancelledError:
            # Request was cancelled
            if queued_successfully:
                await self._metrics.decrement_queued()
                self._queue_semaphore.release()
            raise
