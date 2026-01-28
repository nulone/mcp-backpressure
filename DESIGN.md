# MCP-BACKPRESSURE: Design Document

## Overview

Backpressure and concurrency control middleware for FastMCP MCP servers.

**Problem:** LLMs can generate hundreds of parallel tool calls, causing:
- DoS / resource exhaustion
- Server crashes
- No structured error for clients to retry

**Solution:** Middleware that limits concurrent executions + bounded queue + structured overload errors.

**Reference:** [python-sdk #1698](https://github.com/modelcontextprotocol/python-sdk/issues/1698) (closed as "not planned")

---

## API Contract (frozen for v0.1)

### Public Interface

```python
from mcp_backpressure import BackpressureMiddleware, OverloadError, BackpressureMetrics

mcp = FastMCP("MyServer")
mcp.add_middleware(BackpressureMiddleware(
    max_concurrent=5,        # Required: max parallel tool executions
    queue_size=10,           # Optional: bounded queue (0 = reject immediately)
    queue_timeout=30.0,      # Optional: seconds to wait in queue
    overload_error_code=-32001,  # Optional: JSON-RPC error code
    on_overload=callback,    # Optional: called on each overload
))
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | `int` | **required** | Semaphore size |
| `queue_size` | `int` | `0` | Bounded queue (0 = no queue) |
| `queue_timeout` | `float` | `30.0` | Queue wait timeout (seconds) |
| `overload_error_code` | `int` | `-32001` | JSON-RPC error code |
| `on_overload` | `Callable` | `None` | Callback on overload |

### Error Contract

```json
{
  "code": -32001,
  "message": "SERVER_OVERLOADED",
  "data": {
    "reason": "queue_full | queue_timeout | concurrency_limit",
    "active": 5,
    "queued": 10,
    "max_concurrent": 5,
    "queue_size": 10,
    "queue_timeout_ms": 30000,
    "retry_after_ms": 1000
  }
}
```

---

## Invariants (must hold under ALL conditions)

| ID | Invariant | Test |
|----|-----------|------|
| INV-01 | `active <= max_concurrent` ALWAYS | test_concurrency_limit.py |
| INV-02 | `queued <= queue_size` ALWAYS | test_queue_bound.py |
| INV-03 | Cancel while queued → slot freed | test_cancellation.py |
| INV-04 | Cancel while active → counter decremented | test_cancellation.py |
| INV-05 | Queue timeout → removes item from queue | test_queue_timeout.py |
| INV-06 | After burst → active=0, queued=0 | test_metrics.py |

---

## Scope Gate

### v0.1 (allowed)
- Global max_concurrent
- Bounded queue
- Queue timeout
- Overload error contract
- Simple counters (active/queued/rejected)
- Callback hook

### v0.2+ (forbidden in v0.1)
- Per-client limits
- Per-tool limits
- Fairness/priority scheduling
- Prometheus/OTEL as default dependency
- Circuit breaker
- Size limits
- Distributed limits
- HTTP 429 mapping

---

## Iteration Plan

### Iteration 1: Skeleton + Basic Limit (~600 LOC)
- Repo structure, packaging, CI
- `BackpressureMiddleware(max_concurrent=N)` — semaphore only, no queue
- `OverloadError` with basic payload
- `test_concurrency_limit.py`

**Done when:** N concurrent, N+1 rejected immediately

### Iteration 2: Queue + Timeout + Metrics (~700 LOC)
- Bounded queue implementation
- Queue timeout with cleanup
- Metrics: active/queued/rejected
- `test_queue_bound.py`, `test_queue_timeout.py`, `test_metrics.py`

**Done when:** Queue works, timeout works, metrics accurate

### Iteration 3: Cancellation + Polish (~580 LOC)
- Cancellation correctness (queued + active)
- `test_cancellation.py`, `test_error_payload.py`
- `examples/`
- `README.md`

**Done when:** All invariants hold, Fresh Eyes pass

---

## Fresh Eyes Tasks (pre-release only)

### FE-01: Invariants + Cancellation
- Core correctness: active<=N, queued<=Q
- Cancellation: no permit leaks, no deadlocks

### FE-02: Timeout + Error Contract
- Monotonic time, cleanup on timeout
- Stable error code/message/data

### FE-03: Resource Exhaustion (Adversarial)
- Try to bypass limits
- Memory/task leaks

### FE-04: Transport Smoke
- Works for stdio and HTTP
- No transport-specific assumptions

### FE-05: README/DX
- Quickstart ≤10 lines
- All params documented

### Run Policy
- **When:** Before v0.1.0 release only
- **Max rounds:** 2 (remaining → v0.2 backlog)
- **Fix acceptance:** Must include failing test, diff <50 LOC

---

## Risks

| Risk | Mitigation |
|------|------------|
| FastMCP adds native backpressure | Monitor jlowin/fastmcp issues |
| Concurrency edge cases | Deterministic tests (BarrierTool) |
| Low adoption | Focus on quality, get mentioned in guides |

---

## File Structure

```
mcp-backpressure/
├── src/mcp_backpressure/
│   ├── __init__.py
│   ├── middleware.py      # BackpressureMiddleware
│   ├── limiter.py         # Semaphore + BoundedQueue
│   ├── errors.py          # OverloadError
│   ├── metrics.py         # Counters + callback
│   └── types.py           # Dataclasses
├── tests/
│   ├── conftest.py        # BarrierTool, burst, leak detector
│   ├── test_concurrency_limit.py
│   ├── test_queue_bound.py
│   ├── test_queue_timeout.py
│   ├── test_cancellation.py
│   ├── test_error_payload.py
│   └── test_metrics.py
├── examples/
│   ├── simple_server.py
│   └── load_simulation.py
├── README.md
├── DESIGN.md
├── CHANGELOG.md
├── pyproject.toml
└── .github/workflows/ci.yml
```

---

## Calibration

- **Plan:** 1,880 LOC
- **Multiplier:** 1.20x (concurrency code)
- **Expected actual:** ~2,250 LOC
- **One-shot probability:** 30%
- **Recommended sessions:** 3
