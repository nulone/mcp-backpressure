"""Concurrency limiting primitives for backpressure middleware"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator


class BoundedQueue:
    """
    Bounded queue with timeout support for backpressure control.

    Uses asyncio.Queue with maxsize for bounded behavior.
    Tracks size and provides timeout-aware enqueue/dequeue operations.
    """

    def __init__(self, maxsize: int):
        """
        Create a BoundedQueue.

        Args:
            maxsize: Maximum queue size (must be >= 0)

        Raises:
            ValueError: If maxsize < 0
        """
        if maxsize < 0:
            raise ValueError(f"maxsize must be >= 0, got {maxsize}")

        self._queue: asyncio.Queue[asyncio.Event] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize

    @property
    def maxsize(self) -> int:
        """Get maximum queue size."""
        return self._maxsize

    @property
    def size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()

    def is_full(self) -> bool:
        """Check if queue is full."""
        return self._queue.full()

    async def enqueue(self, timeout: float) -> asyncio.Event:
        """
        Add an item to the queue with timeout.

        Args:
            timeout: Maximum time to wait for queue space (seconds)

        Returns:
            Event that will be set when the item can proceed

        Raises:
            asyncio.TimeoutError: If timeout expires before space becomes available
            asyncio.QueueFull: If queue is full and timeout is 0
        """
        if timeout <= 0:
            # Non-blocking mode
            if self.is_full():
                raise asyncio.QueueFull()

        event = asyncio.Event()
        start_time = time.monotonic()

        try:
            remaining_timeout = timeout
            await asyncio.wait_for(self._queue.put(event), timeout=remaining_timeout)
            return event
        except asyncio.TimeoutError:
            # Timeout expired while waiting for queue space
            elapsed = time.monotonic() - start_time
            raise asyncio.TimeoutError(
                f"Queue enqueue timeout after {elapsed:.2f}s"
            ) from None

    async def dequeue(self) -> asyncio.Event:
        """
        Remove and return an item from the queue.

        Returns:
            Event from the queue
        """
        return await self._queue.get()

    @asynccontextmanager
    async def wait_for_slot(self, timeout: float) -> AsyncIterator[None]:
        """
        Context manager that waits for a slot in the queue.

        Enqueues on entry, dequeues and signals on exit.
        If timeout occurs during enqueue, raises TimeoutError.

        Args:
            timeout: Maximum time to wait for queue space (seconds)

        Yields:
            None

        Raises:
            asyncio.TimeoutError: If timeout expires before getting slot
        """
        # Try to enqueue with timeout
        event = await self.enqueue(timeout)

        try:
            # Wait for the event to be set (item can proceed)
            await event.wait()
            yield
        finally:
            # Dequeue is handled by the middleware after active execution completes
            pass


class ConcurrencyLimiter:
    """
    Combined semaphore + bounded queue for concurrency control.

    Provides two-level limiting:
    1. Semaphore for active execution slots
    2. Bounded queue for waiting requests
    """

    def __init__(self, max_concurrent: int, queue_size: int):
        """
        Create a ConcurrencyLimiter.

        Args:
            max_concurrent: Maximum concurrent executions
            queue_size: Maximum queue size (0 = no queue)

        Raises:
            ValueError: If max_concurrent < 1 or queue_size < 0
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        if queue_size < 0:
            raise ValueError(f"queue_size must be >= 0, got {queue_size}")

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue = BoundedQueue(queue_size) if queue_size > 0 else None
        self._max_concurrent = max_concurrent
        self._queue_size = queue_size

    @property
    def max_concurrent(self) -> int:
        """Get maximum concurrent executions."""
        return self._max_concurrent

    @property
    def queue_size(self) -> int:
        """Get maximum queue size."""
        return self._queue_size

    @property
    def current_queue_size(self) -> int:
        """Get current number of items in queue."""
        return self._queue.size if self._queue else 0

    def semaphore_locked(self) -> bool:
        """Check if all semaphore permits are taken."""
        return self._semaphore.locked()

    def queue_full(self) -> bool:
        """Check if queue is full (or if there is no queue)."""
        if self._queue is None:
            return True
        return self._queue.is_full()

    @asynccontextmanager
    async def acquire(self, queue_timeout: float) -> AsyncIterator[None]:
        """
        Acquire execution slot with queueing support.

        Logic:
        - If semaphore available: acquire immediately
        - If semaphore locked and queue not full: enqueue with timeout
        - If queue full: raise QueueFull
        - If queue timeout: raise TimeoutError

        Args:
            queue_timeout: Maximum time to wait in queue (seconds)

        Yields:
            None

        Raises:
            asyncio.QueueFull: If queue is full
            asyncio.TimeoutError: If queue timeout expires
        """
        # Try to acquire semaphore immediately
        if not self.semaphore_locked():
            async with self._semaphore:
                yield
            return

        # Semaphore is locked, try to queue
        if self._queue is None:
            # No queue configured, reject immediately
            raise asyncio.QueueFull()

        if self.queue_full():
            # Queue is full, reject immediately
            raise asyncio.QueueFull()

        # Enqueue with timeout
        event = await self._queue.enqueue(queue_timeout)

        try:
            # Now wait for semaphore to become available
            async with self._semaphore:
                # Signal the event that we're dequeuing
                await self._queue.dequeue()
                # Set event to allow next queued item to proceed
                if self.current_queue_size > 0:
                    next_event = await self._queue.dequeue()
                    next_event.set()
                yield
        except asyncio.CancelledError:
            # If cancelled while in queue, need to dequeue
            if event and not event.is_set():
                try:
                    # Try to remove from queue
                    await self._queue.dequeue()
                except Exception:
                    pass
            raise
