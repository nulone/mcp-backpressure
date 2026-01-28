"""
Tests for BackpressureMiddleware concurrency limiting.

Verifies INV-01: active <= max_concurrent ALWAYS
"""

import asyncio

import pytest

from mcp_backpressure import BackpressureMiddleware, OverloadError
from tests.conftest import BarrierTool


@pytest.fixture
def middleware():
    """Create middleware with max_concurrent=5 for testing."""
    return BackpressureMiddleware(max_concurrent=5)


@pytest.mark.asyncio
async def test_active_never_exceeds_limit(middleware: BackpressureMiddleware):
    """
    Test INV-01: active <= max_concurrent ALWAYS.

    Launch N+5 concurrent tasks, verify max_seen == N.
    """
    N = middleware.max_concurrent
    barrier_tool = BarrierTool()

    # Create mock call_next that uses barrier
    async def call_next(request):
        return await barrier_tool()

    # Wrap middleware call
    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Launch N+5 tasks
    tasks = [asyncio.create_task(make_request()) for _ in range(N + 5)]

    # Wait for N tasks to enter
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)

    # Give a moment for any over-limit tasks to potentially enter (they shouldn't)
    await asyncio.sleep(0.1)

    # Verify max_seen == N (invariant: never exceeded limit)
    assert barrier_tool.max_seen == N, (
        f"Concurrency limit violated! max_seen={barrier_tool.max_seen}, "
        f"expected={N}"
    )

    # Verify active count matches
    assert middleware.active == N, (
        f"Active count mismatch: middleware.active={middleware.active}, "
        f"expected={N}"
    )

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

    # Verify N succeeded, 5 rejected
    succeeded = [r for r in results if r["ok"]]
    rejected = [r for r in results if not r["ok"]]

    assert len(succeeded) == N, f"Expected {N} successful, got {len(succeeded)}"
    assert len(rejected) == 5, f"Expected 5 rejected, got {len(rejected)}"

    # Verify all rejections were OverloadError
    for r in rejected:
        assert isinstance(r["error"], OverloadError), (
            f"Expected OverloadError, got {type(r['error'])}"
        )

    # Verify active count returns to 0
    assert middleware.active == 0, (
        f"Permit leak detected: active={middleware.active} after all tasks done"
    )


@pytest.mark.asyncio
async def test_rejected_has_correct_error(middleware: BackpressureMiddleware):
    """
    Verify rejected requests have correct error structure.

    - code: -32001
    - message: 'SERVER_OVERLOADED'
    - reason: 'concurrency_limit'
    - data fields: active, max_concurrent
    """
    N = middleware.max_concurrent
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Fill all permits
    tasks = [asyncio.create_task(make_request()) for _ in range(N)]
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)

    # Now try one more - should be rejected
    try:
        await make_request()
        pytest.fail("Expected OverloadError but request succeeded")
    except OverloadError as e:
        # Verify error structure
        assert e.code == -32001, f"Expected code=-32001, got {e.code}"
        assert e.message == "SERVER_OVERLOADED", (
            f"Expected message='SERVER_OVERLOADED', got '{e.message}'"
        )
        assert e.reason == "concurrency_limit", (
            f"Expected reason='concurrency_limit', got '{e.reason}'"
        )

        # Verify data fields
        assert e.active == N, f"Expected active={N}, got {e.active}"
        assert e.max_concurrent == N, (
            f"Expected max_concurrent={N}, got {e.max_concurrent}"
        )

        # Verify to_json_rpc() format
        json_rpc = e.to_json_rpc()
        assert "code" in json_rpc
        assert "message" in json_rpc
        assert "data" in json_rpc
        assert json_rpc["code"] == -32001
        assert json_rpc["message"] == "SERVER_OVERLOADED"
        assert json_rpc["data"]["reason"] == "concurrency_limit"
        assert json_rpc["data"]["active"] == N
        assert json_rpc["data"]["max_concurrent"] == N

    finally:
        # Cleanup: release barrier
        barrier_tool.release()
        for task in tasks:
            try:
                await task
            except Exception:
                pass

    # Verify no leaks
    assert middleware.active == 0


@pytest.mark.asyncio
async def test_sequential_requests_all_succeed(middleware: BackpressureMiddleware):
    """Verify sequential requests (no concurrency) all succeed."""

    async def call_next(request):
        await asyncio.sleep(0.01)
        return {"result": "ok"}

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Execute 20 sequential requests
    for i in range(20):
        result = await make_request()
        assert result["result"] == "ok", f"Request {i} failed"

    # Verify no leaks
    assert middleware.active == 0


@pytest.mark.asyncio
async def test_burst_under_limit_all_succeed(middleware: BackpressureMiddleware):
    """Verify burst of N requests (at limit) all succeed."""
    N = middleware.max_concurrent

    async def call_next(request):
        await asyncio.sleep(0.05)
        return {"result": "ok"}

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Launch exactly N concurrent requests
    tasks = [asyncio.create_task(make_request()) for _ in range(N)]

    # All should succeed
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        assert not isinstance(result, Exception), (
            f"Task {i} failed: {result}"
        )
        assert result["result"] == "ok"

    # Verify no leaks
    assert middleware.active == 0


@pytest.mark.asyncio
async def test_middleware_validates_max_concurrent():
    """Verify middleware rejects invalid max_concurrent values."""
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        BackpressureMiddleware(max_concurrent=0)

    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        BackpressureMiddleware(max_concurrent=-1)


@pytest.mark.asyncio
async def test_active_count_accuracy(middleware: BackpressureMiddleware):
    """Verify active counter accurately tracks concurrent executions."""
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Start with 0
    assert middleware.active == 0

    # Launch 3 tasks
    tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await barrier_tool.wait_entered_at_least(3, timeout=2.0)

    # Should show 3 active
    assert middleware.active == 3

    # Release and wait for completion
    barrier_tool.release()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Should return to 0
    assert middleware.active == 0
