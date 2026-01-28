# DECISIONS

## Architecture Decisions

### AD-001: Project Type - library
**Decision:** Build as a library project.
**Rationale:** Per project.yaml specification.
**Date:** 2026-01-28 13:50:21 UTC

### AD-002: Language - python
**Decision:** Use python as the primary language.
**Rationale:** Per project.yaml specification.
**Date:** 2026-01-28 13:50:21 UTC

### AD-003: MVP Scope
**Decision:**
Global concurrency limit (max_concurrent), bounded queue (queue_size), 
queue timeout, structured overload error (JSON-RPC -32001).
NO per-client limits, NO fairness, NO prometheus.


**Rationale:** Clear scope boundaries prevent scope creep.
**Date:** 2026-01-28 13:50:21 UTC

## Technology Choices

### Dependencies
Runtime:
- fastmcp>=2.9.0

Development:
- pytest>=8.0
- pytest-asyncio>=0.23
- ruff>=0.4
- mypy>=1.10
- pytest-cov>=5.0

## Future Decisions
_Record additional architectural decisions here as the project evolves._
