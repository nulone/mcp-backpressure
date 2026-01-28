# PLAN — Iteration 1

## Estimates
- LOC: ~903
- Time: ~13 min
- Context: ~55%
- Sessions: 1

## Tasks (in order)

### Setup
1. [ ] Bootstrap: venv, pyproject.toml, directories
2. [ ] Create test fixtures

### Implementation
3. [ ] Module: core
4. [ ] Module: tests
5. [ ] Module: examples
6. [ ] Module: docs
7. [ ] Module: packaging
8. [ ] Write tests

### Validation (MANDATORY — DO NOT SKIP)
9. [ ] Run: ./.venv/bin/python -m pytest tests/ -v
10. [ ] Run: ./.venv/bin/ruff check src/ tests/
11. [ ] Run: codex review --uncommitted
12. [ ] Run: codex review "Adversarial: try to BREAK this code. P1/P2/P3."
13. [ ] Run: gemini_review.sh basic .
14. [ ] Run: gemini_review.sh adversarial .
15. [ ] Fix ALL P1 issues
16. [ ] Document P2/P3 in BUGS.md

## Exit Criteria
- [ ] All tests pass
- [ ] No P1 bugs from any validator
- [ ] P2/P3 documented
- [ ] README updated
- [ ] All validation steps completed
