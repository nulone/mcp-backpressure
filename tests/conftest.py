# =============================================================================
# TEST FIXTURES FOR MCP-BACKPRESSURE
# Deterministic concurrency testing + permit leak detection
# =============================================================================

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# BARRIER TOOL - deterministic "hold and release" for concurrency tests
# =============================================================================

@dataclass
class BarrierTool:
    """
    Deterministic tool for concurrency tests.
    Holds execution until explicitly released.
    """
    entered: int = 0
    max_seen: int = 0
    _active: int = 0

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _entered_event: asyncio.Event = field(default_factory=asyncio.Event)
    _release_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self) -> dict:
        async with self._lock:
            self.entered += 1
            self._active += 1
            if self._active > self.max_seen:
                self.max_seen = self._active
            self._entered_event.set()

        try:
            await self._release_event.wait()
            return {"ok": True}
        finally:
            async with self._lock:
                self._active -= 1

    async def wait_entered_at_least(self, n: int, timeout: float = 2.0) -> None:
        end = asyncio.get_running_loop().time() + timeout
        while True:
            async with self._lock:
                if self.entered >= n:
                    return
                self._entered_event.clear()

            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timeout waiting for entered >= {n}, got {self.entered}")

            try:
                await asyncio.wait_for(self._entered_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout waiting for entered >= {n}, got {self.entered}") from None

    def release(self) -> None:
        self._release_event.set()

    async def get_active(self) -> int:
        async with self._lock:
            return self._active

    def reset(self) -> None:
        self.entered = 0
        self.max_seen = 0
        self._active = 0
        self._entered_event = asyncio.Event()
        self._release_event = asyncio.Event()


# =============================================================================
# CALL RESULT - structured result from burst
# =============================================================================

@dataclass
class CallResult:
    ok: bool
    value: Any = None
    exc: BaseException | None = None

    @property
    def is_overload(self) -> bool:
        if self.exc is None:
            return False
        exc_name = type(self.exc).__name__.lower()
        exc_str = str(self.exc).lower()
        return "overload" in exc_name or "overload" in exc_str

    @property
    def is_cancelled(self) -> bool:
        return isinstance(self.exc, asyncio.CancelledError)

    @property
    def is_timeout(self) -> bool:
        if self.exc is None:
            return False
        return "timeout" in str(self.exc).lower()


# =============================================================================
# BURST - launch N concurrent calls
# =============================================================================

async def burst(
    call: Callable[[], Awaitable[Any]],
    n: int,
    *,
    cancel_indices: list[int] | None = None,
    cancel_after: float = 0.0,
) -> list[CallResult]:
    """
    Launch n concurrent calls and collect results.
    Optionally cancel specific tasks by index.
    """
    cancel_indices = cancel_indices or []
    tasks = [asyncio.create_task(call()) for _ in range(n)]

    await asyncio.sleep(0)  # Let tasks start

    if cancel_indices:
        if cancel_after > 0:
            await asyncio.sleep(cancel_after)
        for i in cancel_indices:
            if 0 <= i < len(tasks):
                tasks[i].cancel()

    results: list[CallResult] = []
    for t in tasks:
        try:
            v = await t
            results.append(CallResult(ok=True, value=v))
        except asyncio.CancelledError as e:
            results.append(CallResult(ok=False, exc=e))
        except BaseException as e:
            results.append(CallResult(ok=False, exc=e))

    return results


# =============================================================================
# PERMIT LEAK DETECTOR - catches zombies after test
# =============================================================================

class PermitLeakDetector:
    """
    Detects permit/slot leaks after test completion.
    
    Usage:
        detector = PermitLeakDetector(middleware)
        
        # ... run test ...
        
        await detector.assert_clean(timeout=1.0)
    """

    def __init__(self, middleware):
        self.middleware = middleware

    async def assert_clean(self, timeout: float = 1.0, msg: str = "Permit leak detected") -> None:
        """Assert that active=0 and queued=0 after test."""
        end = asyncio.get_running_loop().time() + timeout

        while True:
            metrics = self._get_metrics()
            if metrics["active"] == 0 and metrics["queued"] == 0:
                return

            if asyncio.get_running_loop().time() >= end:
                raise AssertionError(
                    f"{msg}: active={metrics['active']}, queued={metrics['queued']} "
                    f"(expected both 0)"
                )

            await asyncio.sleep(0.01)

    def _get_metrics(self) -> dict:
        """Get metrics from middleware. Adapt to your API."""
        # Option 1: middleware.get_metrics() returns dataclass
        if hasattr(self.middleware, 'get_metrics'):
            m = self.middleware.get_metrics()
            return {"active": m.active, "queued": m.queued}

        # Option 2: direct attributes
        if hasattr(self.middleware, 'active'):
            return {
                "active": self.middleware.active,
                "queued": getattr(self.middleware, 'queued', 0)
            }

        # Fallback
        return {"active": 0, "queued": 0}


@asynccontextmanager
async def leak_detector(middleware):
    """
    Context manager that asserts no leaks on exit.
    
    Usage:
        async with leak_detector(middleware):
            # ... run test ...
        # Automatically asserts active=0, queued=0
    """
    detector = PermitLeakDetector(middleware)
    try:
        yield detector
    finally:
        await detector.assert_clean(msg="Test left permits leaked")


# =============================================================================
# ASSERT EVENTUALLY - for metrics checks (use sparingly)
# =============================================================================

async def assert_eventually(
    pred: Callable[[], Awaitable[bool]],
    *,
    timeout: float = 1.0,
    tick: float = 0.01,
    msg: str = "Condition not met",
) -> None:
    """
    Assert async predicate becomes True within timeout.
    Use sparingly - prefer deterministic waits.
    """
    end = asyncio.get_running_loop().time() + timeout
    while True:
        if await pred():
            return
        if asyncio.get_running_loop().time() >= end:
            raise AssertionError(f"{msg} within {timeout}s")
        await asyncio.sleep(tick)


# =============================================================================
# PYTEST FIXTURES
# =============================================================================

import pytest


@pytest.fixture
def barrier_tool():
    return BarrierTool()

@pytest.fixture
def middleware():
    """
    Create middleware for testing.
    Replace with actual:
    
    from mcp_backpressure import BackpressureMiddleware
    return BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=2.0)
    """
    pass

@pytest.fixture
async def detector(middleware):
    """Leak detector that auto-checks on test exit."""
    async with leak_detector(middleware) as d:
        yield d


# =============================================================================
# EXAMPLE TEST WITH LEAK DETECTION
# =============================================================================

"""
@pytest.mark.asyncio
async def test_no_leaks_after_burst(middleware, barrier_tool, detector):
    N = 5
    
    async def call():
        return await middleware.call_tool(barrier_tool)
    
    tasks = [asyncio.create_task(call()) for _ in range(N + 5)]
    
    await barrier_tool.wait_entered_at_least(N)
    assert barrier_tool.max_seen == N
    
    barrier_tool.release()
    
    for t in tasks:
        try:
            await t
        except Exception:
            pass
    
    # detector.assert_clean() called automatically on exit
"""
