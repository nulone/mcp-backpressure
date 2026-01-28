# mcp-backpressure

Backpressure/concurrency control middleware for FastMCP MCP servers

## Project Type
library

## MVP Scope
Global concurrency limit (max_concurrent), bounded queue (queue_size), 
queue timeout, structured overload error (JSON-RPC -32001).
NO per-client limits, NO fairness, NO prometheus.


## Setup

```bash
# Create virtual environment
python3 -m venv .venv

# Activate venv
source .venv/bin/activate  # On Unix/macOS
# or
.venv\Scripts\activate  # On Windows

# Install dependencies
pip install -e ".[dev]"
```

## Usage

_To be documented_

## Development

### Running Tests

```bash
./.venv/bin/python -m pytest tests/ -v
```

### Linting

```bash
./.venv/bin/ruff check src/ tests/
```

### Full Validation

```bash
./scripts/review_all.sh .
```

## Modules
### core
Main middleware, limiter, errors, metrics, types
### tests
Unit tests for concurrency, queue, timeout, cancellation
### examples
Simple server and load simulation examples
### docs
README, DESIGN.md, CHANGELOG
### packaging
pyproject.toml, CI workflow, py.typed

## Success Criteria
- All tests pass
- No P1 bugs from validation
- P2/P3 documented in BUGS.md

---

Generated with [agent-boilerplate](https://github.com/yourusername/agent-boilerplate) v0.1.0
