1) Ship verdict: NO — cancellation can leak execution or queue permits before the cleanup path runs, which can permanently reduce capacity or deadlock under load.

2) Findings table:
| Severity | File+line | Issue | Why it matters | How to verify |
| --- | --- | --- | --- | --- |
| P1 | `src/mcp_backpressure/middleware.py:136`, `src/mcp_backpressure/middleware.py:137`, `src/mcp_backpressure/middleware.py:188`, `src/mcp_backpressure/middleware.py:189` | Cancellation before the main `try/except` can leak execution permits or queue slots (e.g., cancelled during `sleep(0)` leaves `acquire_task` alive; cancelled during `increment_queued` leaves queue slot held). | Leaked permits shrink effective `max_concurrent` or block queue admission, violating cancellation safety and invariants (INV‑03/INV‑06) and causing spurious overloads. | Add a deterministic test that cancels immediately after creating the middleware task (before `sleep(0)` returns) and another that cancels while `increment_queued` is blocked (e.g., monkeypatch to await an event); then assert subsequent requests still reach full concurrency and `active/queued` return to 0. |
| P2 | `src/mcp_backpressure/middleware.py:164`, `src/mcp_backpressure/middleware.py:183`, `src/mcp_backpressure/middleware.py:251` | `on_overload` callback exceptions are not isolated, so a raised exception replaces `OverloadError`. | Breaks JSON-RPC error payload stability under overload and can surface unexpected exceptions to clients. | Set `on_overload` to a function that raises and confirm overload responses still return structured `OverloadError` payloads. |

3) Must-fix list (max 10)
- Wrap the entire admission path (including `sleep(0)`, queue slot acquire, and `increment_queued`) in cancellation-safe `try/finally` so `acquire_task` is cancelled/awaited and queue slots are released on early cancellation.
- Ensure queue-slot acquisition sets a cleanup guard before any await after acquiring the slot (e.g., set `queued_successfully = True` immediately after acquire or guard with `try/finally` around `increment_queued`).

4) Nice-to-have list (max 10)
- Guard `on_overload` with a `try/except` so callback failures don’t replace the structured overload error.
- Add targeted tests for cancellation during pre-try admission (before `sleep(0)` completes) and during `increment_queued`, to lock in the fix.

Assumptions: Single-threaded asyncio event loop semantics; no external thread manipulates semaphores.
