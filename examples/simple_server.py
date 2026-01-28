"""
Minimal FastMCP server with backpressure middleware.

Demonstrates basic usage of BackpressureMiddleware for protecting
server resources from concurrent request overload.

Run:
    python examples/simple_server.py
"""

import asyncio

from fastmcp import FastMCP

from mcp_backpressure import BackpressureMiddleware

# Create server
mcp = FastMCP("DemoServer")

# Add backpressure middleware
mcp.add_middleware(
    BackpressureMiddleware(
        max_concurrent=5,  # Allow max 5 concurrent executions
        queue_size=10,  # Queue up to 10 waiting requests
        queue_timeout=30.0,  # Wait max 30s in queue
    )
)


@mcp.tool()
async def slow_operation(duration: float = 1.0) -> dict:
    """Simulate a slow operation."""
    await asyncio.sleep(duration)
    return {"result": "completed", "duration": duration}


@mcp.tool()
async def fast_operation(value: str) -> dict:
    """Fast operation that returns immediately."""
    return {"echo": value}


if __name__ == "__main__":
    # Start server (stdio transport)
    mcp.run()
