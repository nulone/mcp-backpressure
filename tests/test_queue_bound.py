"""
Tests for queue bound limiting.

Verifies INV-02: queued <= queue_size ALWAYS
"""

import asyncio

import pytest

from mcp_backpressure import BackpressureMiddleware, OverloadError
from tests.conftest import BarrierTool


@pytest.fixture
def middleware():
    """Create middleware with max_concurrent=3, queue_size=5 for testing."""
    return BackpressureMiddleware(max_concurrent=3, queue_size=5, queue_timeout=10.0)


@pytest.mark.asyncio
async def test_queued_never_exceeds_limit(middleware: BackpressureMiddleware):
    """
    Test INV-02: queued <= queue_size ALWAYS.

    Launch N+Q+3 concurrent tasks where:
    - N = max_concurrent (will be active)
    - Q = queue_size (will be queued)
    - 3 = should be rejected

    Verify queued never exceeds queue_size.
    """
    N = middleware.max_concurrent
    Q = middleware.queue_size
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Launch N+Q+3 tasks
    total_tasks = N + Q + 3
    tasks = [asyncio.create_task(make_request()) for _ in range(total_tasks)]

    # Wait for N tasks to enter (active)
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)

    # Give a moment for queue to fill
    await asyncio.sleep(0.1)

    # Verify invariants
    assert middleware.active <= N, f"INV-01 violated: active={middleware.active} > {N}"
    assert middleware.queued <= Q, f"INV-02 violated: queued={middleware.queued} > {Q}"

    # Expected state: N active, Q queued, 3 rejected
    metrics = middleware.get_metrics()
    assert metrics.active == N, f"Expected active={N}, got {metrics.active}"
    assert metrics.queued == Q, f"Expected queued={Q}, got {metrics.queued}"

    # Release barrier to let tasks complete
    barrier_tool.release()

    # Collect results
    results = []
    for task in tasks:
        try:
            result = await task
            results.append({"ok": True, "value": result})
        except OverloadError as e:
            results.append({"ok": False, "error": e})
        except Exception as e:
            results.append({"ok": False, "error": e})

    # Verify N+Q succeeded, 3 rejected
    succeeded = [r for r in results if r["ok"]]
    rejected = [r for r in results if not r["ok"]]

    assert len(succeeded) == N + Q, f"Expected {N+Q} successful, got {len(succeeded)}"
    assert len(rejected) == 3, f"Expected 3 rejected, got {len(rejected)}"

    # Verify all rejections were OverloadError with reason='queue_full'
    for r in rejected:
        assert isinstance(r["error"], OverloadError), (
            f"Expected OverloadError, got {type(r['error'])}"
        )
        assert r["error"].reason == "queue_full", (
            f"Expected reason='queue_full', got '{r['error'].reason}'"
        )

    # Verify final state: active=0, queued=0
    metrics = middleware.get_metrics()
    assert metrics.active == 0, f"Permit leak: active={metrics.active}"
    assert metrics.queued == 0, f"Queue leak: queued={metrics.queued}"


@pytest.mark.asyncio
async def test_queue_full_rejection_immediate(middleware: BackpressureMiddleware):
    """
    Test that when queue is full, new requests are rejected immediately.

    No timeout wait should occur - rejection should be instant.
    """
    N = middleware.max_concurrent
    Q = middleware.queue_size
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Fill active + queue
    tasks = [asyncio.create_task(make_request()) for _ in range(N + Q)]

    # Wait for N tasks to enter
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)
    await asyncio.sleep(0.1)

    # Now try one more - should be rejected immediately
    import time

    start = time.monotonic()
    try:
        await make_request()
        pytest.fail("Expected OverloadError but request succeeded")
    except OverloadError as e:
        elapsed = time.monotonic() - start
        assert e.reason == "queue_full"
        # Should be rejected in < 100ms (no queue timeout wait)
        assert elapsed < 0.1, f"Rejection took too long: {elapsed:.3f}s"

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass

    # Verify no leaks
    metrics = middleware.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_queue_size_zero_rejects_immediately(middleware: BackpressureMiddleware):
    """
    Test that queue_size=0 means no queueing - reject at concurrency limit.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=0, queue_timeout=10.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Next request should be rejected immediately (no queue)
    try:
        await make_request()
        pytest.fail("Expected OverloadError but request succeeded")
    except OverloadError as e:
        assert e.reason == "concurrency_limit"
        assert e.queued == 0
        assert e.queue_size == 0

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass

    metrics = mw.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_queue_drains_correctly(middleware: BackpressureMiddleware):
    """
    Test that queued requests are processed in order as active slots free up.
    """
    N = middleware.max_concurrent
    Q = middleware.queue_size
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Launch N+Q tasks (fill active + queue)
    tasks = [asyncio.create_task(make_request()) for _ in range(N + Q)]

    # Wait for N to be active
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)
    await asyncio.sleep(0.1)

    # Verify state
    assert middleware.active == N
    assert middleware.queued == Q

    # Release barrier - queue should drain
    barrier_tool.release()

    # Wait for all to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All should succeed
    for i, result in enumerate(results):
        assert not isinstance(result, Exception), f"Task {i} failed: {result}"

    # Verify final state
    metrics = middleware.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_error_payload_queue_full():
    """
    Verify error payload for queue_full has correct fields.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=3, queue_timeout=5.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active + queue
    tasks = [asyncio.create_task(make_request()) for _ in range(2 + 3)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    await asyncio.sleep(0.1)

    # Try one more
    try:
        await make_request()
        pytest.fail("Expected OverloadError")
    except OverloadError as e:
        assert e.reason == "queue_full"
        assert e.active == 2
        assert e.queued == 3
        assert e.max_concurrent == 2
        assert e.queue_size == 3
        assert e.queue_timeout_ms == 5000
        assert e.code == -32001
        assert e.message == "SERVER_OVERLOADED"

        # Check JSON-RPC format
        json_rpc = e.to_json_rpc()
        assert json_rpc["code"] == -32001
        assert json_rpc["message"] == "SERVER_OVERLOADED"
        assert json_rpc["data"]["reason"] == "queue_full"
        assert json_rpc["data"]["active"] == 2
        assert json_rpc["data"]["queued"] == 3

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_concurrent_queue_operations():
    """
    Test concurrent enqueue/dequeue operations maintain invariants.

    Rapidly launch and complete many requests to stress-test queue.
    """
    mw = BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=5.0)

    async def call_next(request):
        await asyncio.sleep(0.01)
        return {"ok": True}

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Launch many concurrent requests
    tasks = [asyncio.create_task(make_request()) for _ in range(50)]

    # Let them run
    await asyncio.sleep(0.05)

    # Check invariants periodically
    for _ in range(5):
        metrics = mw.get_metrics()
        assert metrics.active <= 5, f"INV-01 violated: active={metrics.active}"
        assert metrics.queued <= 10, f"INV-02 violated: queued={metrics.queued}"
        await asyncio.sleep(0.02)

    # Wait for completion
    await asyncio.gather(*tasks, return_exceptions=True)

    # Final check
    metrics = mw.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0
