"""Backpressure middleware for FastMCP servers"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import OverloadError


class BackpressureMiddleware:
    """
    Middleware that limits concurrent request executions using a semaphore.

    When max_concurrent is reached, new requests are rejected immediately
    with OverloadError.

    Example:
        mcp = FastMCP("MyServer")
        mcp.add_middleware(BackpressureMiddleware(max_concurrent=5))
    """

    def __init__(self, max_concurrent: int):
        """
        Create a BackpressureMiddleware.

        Args:
            max_concurrent: Maximum number of concurrent request executions

        Raises:
            ValueError: If max_concurrent < 1
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")

        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> int:
        """Get current number of active requests."""
        return self._active

    async def __call__(
        self,
        request: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """
        Process request with concurrency limiting.

        Args:
            request: The incoming request
            call_next: Function to call next middleware/handler

        Returns:
            Response from call_next

        Raises:
            OverloadError: If semaphore is at capacity (concurrency limit reached)
        """
        # Check if semaphore is locked (all permits taken)
        if self._semaphore.locked():
            # Read current active count for error message
            async with self._lock:
                current_active = self._active

            # Reject immediately with overload error
            raise OverloadError(
                reason="concurrency_limit",
                active=current_active,
                max_concurrent=self.max_concurrent,
            )

        # Acquire semaphore permit
        async with self._semaphore:
            # Increment active counter
            async with self._lock:
                self._active += 1

            try:
                # Execute the actual request handler
                return await call_next(request)
            finally:
                # Decrement active counter
                async with self._lock:
                    self._active -= 1
