"""
Load simulation demonstrating backpressure behavior under heavy load.

Simulates concurrent client requests to show how BackpressureMiddleware
handles overload scenarios with queueing and rejection.

Run:
    python examples/load_simulation.py
"""

import asyncio
import time
from typing import Any

from mcp_backpressure import BackpressureMiddleware, OverloadError


class SimulatedTool:
    """Simulates a tool that takes time to execute."""

    def __init__(self, duration: float = 0.5):
        self.duration = duration
        self.completed = 0

    async def execute(self) -> dict:
        """Simulate work."""
        await asyncio.sleep(self.duration)
        self.completed += 1
        return {"status": "completed", "id": self.completed}


async def simulate_request(
    middleware: BackpressureMiddleware,
    tool: SimulatedTool,
    request_id: int,
) -> dict:
    """Simulate a single request through middleware."""

    async def call_next(request: Any) -> dict:
        return await tool.execute()

    fake_request = {"id": request_id, "tool": "simulate"}
    return await middleware(fake_request, call_next)


async def run_simulation():
    """Run load simulation."""
    print("=" * 60)
    print("MCP Backpressure Load Simulation")
    print("=" * 60)

    # Create middleware with limits
    MAX_CONCURRENT = 5
    QUEUE_SIZE = 10
    QUEUE_TIMEOUT = 2.0

    middleware = BackpressureMiddleware(
        max_concurrent=MAX_CONCURRENT,
        queue_size=QUEUE_SIZE,
        queue_timeout=QUEUE_TIMEOUT,
        on_overload=lambda e: print(
            f"⚠️  OVERLOAD: {e.reason} (active={e.active}, queued={e.queued})"
        ),
    )

    # Create simulated tool
    tool = SimulatedTool(duration=1.0)

    print("\nConfiguration:")
    print(f"  max_concurrent: {MAX_CONCURRENT}")
    print(f"  queue_size: {QUEUE_SIZE}")
    print(f"  queue_timeout: {QUEUE_TIMEOUT}s")
    print(f"  tool_duration: {tool.duration}s")

    # Simulate burst of requests
    NUM_REQUESTS = 30
    print(f"\n🚀 Launching {NUM_REQUESTS} concurrent requests...")
    print(f"   Expected: {MAX_CONCURRENT} active, {QUEUE_SIZE} queued, "
          f"{NUM_REQUESTS - MAX_CONCURRENT - QUEUE_SIZE} rejected\n")

    start_time = time.monotonic()

    async def make_request(req_id: int) -> dict:
        try:
            result = await simulate_request(middleware, tool, req_id)
            return {"id": req_id, "status": "success", "result": result}
        except OverloadError as e:
            return {
                "id": req_id,
                "status": "overload",
                "reason": e.reason,
                "error": e.to_json_rpc(),
            }
        except Exception as e:
            return {"id": req_id, "status": "error", "error": str(e)}

    # Launch all requests concurrently
    tasks = [asyncio.create_task(make_request(i)) for i in range(NUM_REQUESTS)]

    # Show metrics during execution
    print("Monitoring metrics:")
    metrics_task = asyncio.create_task(monitor_metrics(middleware, duration=3.0))

    # Wait for all requests to complete
    results = await asyncio.gather(*tasks)

    # Stop metrics monitoring
    metrics_task.cancel()
    try:
        await metrics_task
    except asyncio.CancelledError:
        pass

    elapsed = time.monotonic() - start_time

    # Analyze results
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    successful = [r for r in results if r["status"] == "success"]
    overloaded = [r for r in results if r["status"] == "overload"]
    errors = [r for r in results if r["status"] == "error"]

    print(f"\n✅ Successful: {len(successful)}")
    print(f"⚠️  Overloaded: {len(overloaded)}")
    print(f"❌ Errors: {len(errors)}")

    if overloaded:
        # Group by reason
        reasons = {}
        for r in overloaded:
            reason = r["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1

        print("\nOverload reasons:")
        for reason, count in reasons.items():
            print(f"  - {reason}: {count}")

    # Show final metrics
    final_metrics = middleware.get_metrics()
    print("\nFinal metrics:")
    print(f"  active: {final_metrics.active}")
    print(f"  queued: {final_metrics.queued}")
    print(f"  total_rejected: {final_metrics.total_rejected}")
    print(f"  rejected_concurrency_limit: {final_metrics.rejected_concurrency_limit}")
    print(f"  rejected_queue_full: {final_metrics.rejected_queue_full}")
    print(f"  rejected_queue_timeout: {final_metrics.rejected_queue_timeout}")

    print(f"\n⏱️  Total time: {elapsed:.2f}s")
    print(f"🎯 Completed executions: {tool.completed}")

    # Show example error payload
    if overloaded:
        print("\n" + "=" * 60)
        print("Example Overload Error Payload (JSON-RPC)")
        print("=" * 60)
        import json

        example_error = overloaded[0]["error"]
        print(json.dumps(example_error, indent=2))

    print("\n" + "=" * 60)


async def monitor_metrics(middleware: BackpressureMiddleware, duration: float):
    """Monitor and print metrics during simulation."""
    end_time = asyncio.get_running_loop().time() + duration
    while asyncio.get_running_loop().time() < end_time:
        metrics = await middleware.get_metrics_async()
        print(
            f"  [metrics] active={metrics.active}, queued={metrics.queued}, "
            f"rejected={metrics.total_rejected}"
        )
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(run_simulation())
