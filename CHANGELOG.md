# Changelog

## [0.1.0] - 2026-02-02

### Added
- `BackpressureMiddleware` with `max_concurrent`, `queue_size`, `queue_timeout`
- `OverloadError` with JSON-RPC format (code -32001)
- `BackpressureMetrics` for tracking active/queued/rejected
- 51 tests with deterministic concurrency testing
- Examples: `simple_server.py`, `load_simulation.py`

### Fixed
- Race condition in semaphore admission (TOCTOU)
- Permit leak on exceptions
- Metrics ordering for accurate error payloads
