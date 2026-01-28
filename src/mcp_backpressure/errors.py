"""Error classes for mcp-backpressure middleware"""

from typing import Any


class OverloadError(Exception):
    """
    Raised when server is overloaded and cannot accept more requests.

    Follows JSON-RPC error format for MCP protocol.
    """

    def __init__(
        self,
        reason: str,
        active: int,
        max_concurrent: int,
        code: int = -32001,
        message: str = "SERVER_OVERLOADED",
        queued: int = 0,
        queue_size: int = 0,
        queue_timeout_ms: int = 0,
        retry_after_ms: int = 1000,
    ):
        """
        Create an OverloadError.

        Args:
            reason: Overload reason ('concurrency_limit', 'queue_full', 'queue_timeout')
            active: Number of currently active requests
            max_concurrent: Maximum allowed concurrent requests
            code: JSON-RPC error code (default: -32001)
            message: Error message (default: 'SERVER_OVERLOADED')
            queued: Number of requests in queue (default: 0)
            queue_size: Maximum queue size (default: 0)
            queue_timeout_ms: Queue timeout in milliseconds (default: 0)
            retry_after_ms: Suggested retry delay in milliseconds (default: 1000)
        """
        self.code = code
        self.message = message
        self.reason = reason
        self.active = active
        self.max_concurrent = max_concurrent
        self.queued = queued
        self.queue_size = queue_size
        self.queue_timeout_ms = queue_timeout_ms
        self.retry_after_ms = retry_after_ms

        super().__init__(f"{message}: {reason}")

    @property
    def data(self) -> dict[str, Any]:
        """Get error data payload."""
        return {
            "reason": self.reason,
            "active": self.active,
            "queued": self.queued,
            "max_concurrent": self.max_concurrent,
            "queue_size": self.queue_size,
            "queue_timeout_ms": self.queue_timeout_ms,
            "retry_after_ms": self.retry_after_ms,
        }

    def to_json_rpc(self) -> dict[str, Any]:
        """
        Convert to JSON-RPC error object.

        Returns:
            dict with 'code', 'message', and 'data' keys
        """
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
        }
