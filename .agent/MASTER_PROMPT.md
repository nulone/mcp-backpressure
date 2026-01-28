# Master Prompt: mcp-backpressure

> Copy this entire prompt to Claude CLI to start implementation

---

## Your Mission

Implement **mcp-backpressure** — Backpressure/concurrency control middleware for FastMCP MCP servers

**Estimated scope:**
- ~903 lines of code
- ~13 minutes
- ~55% context usage


---

## Step 1: Read Project Files

```bash
cat .agent/AGENTS.md    # Rules and requirements
cat .agent/PLAN.md      # Task breakdown
cat .agent/DECISIONS.md # Architecture decisions
```

---

## Step 2: Setup Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Step 3: Implement

Follow PLAN.md task by task:
1. Write test first (TDD)
2. Implement to pass test
3. Mark task complete in STATE.md
4. **Check context usage after every 3-4 files!**

---

## Step 4: MANDATORY Validation

**⚠️ You MUST run these before saying "complete":**

```bash
# 1. Tests (REQUIRED)
pytest tests/ -v --tb=short 2>&1 | tail -40

# 2. Lint (REQUIRED)  
ruff check src/ tests/

# 3. Gemini review (if available)
./scripts/gemini_review.sh basic . 2>/dev/null || echo "Gemini: skipped (no API key)"
```

### Validation Rules:

| Check | Required | On Failure |
|-------|----------|------------|
| pytest | ✅ Yes | Fix and retry (max 3 attempts) |
| ruff | ✅ Yes | Fix and retry (max 3 attempts) |
| gemini | ⚠️ Optional | Document P1/P2 bugs in BUGS.md |

### If tests/lint fail:
1. **Attempt 1:** Fix the issue, re-run
2. **Attempt 2:** Fix again if still failing
3. **Attempt 3:** Final attempt
4. **After 3 failures:** Document in BUGS.md, report to user

### Do NOT mark complete until:
- [ ] All pytest tests pass
- [ ] All ruff checks pass
- [ ] Gemini findings documented (if ran)

---

## Step 5: Complete

1. Update AGENT_LOG.md with session summary
2. Ensure all STATE.md tasks checked
3. List any bugs in BUGS.md

---

## ⚠️ CONTEXT LIMIT WARNING


**This project may approach context limits!**

Estimated usage: ~55%
Checkpoint threshold: 60%


**CRITICAL:** If you reach ~60% context usage:

1. STOP implementation immediately
2. Update STATE.md with current progress
3. Commit: `git add -A && git commit -m "checkpoint: progress"`
4. Say: "⚠️ CHECKPOINT REACHED — continue with RESUME_PROMPT.md"
5. Do NOT continue — wait for new session

Signs you're approaching limit:
- Written 500+ LOC
- Long conversation with many back-and-forths
- Multiple debugging cycles

---

## ⚠️ CONTEXT MONITORING (CRITICAL)

**You CANNOT accurately estimate your own context usage!**
Your internal estimate is ~2x lower than reality.

### Use `/context` command to check real usage:
```
/context
```

This shows: `XXk/200k tokens (XX%)`

### Context Rules:

| `/context` shows | Action |
|------------------|--------|
| < 40% | ✅ Continue normally |
| 40-50% | ⚠️ Check after each module |
| 50-55% | 🛑 STOP after current module |
| > 55% | 🚨 CHECKPOINT NOW |

### Mandatory `/context` checks:
- After every 2-3 modules
- Before starting a complex module
- If conversation feels long

**Remember:** Real limit is ~77% (autocompact buffer = 22.5%)
Checkpoint at 55% leaves safety margin.


---

## Quick Reference

| File | Purpose |
|------|---------|
| `.agent/AGENTS.md` | Rules, validation requirements |
| `.agent/PLAN.md` | Task list with estimates |
| `.agent/STATE.md` | Progress tracking (update this!) |
| `.agent/DECISIONS.md` | Architecture decisions |
| `.agent/RESUME_PROMPT.md` | Use if session interrupted |
| `BUGS.md` | Track P1/P2/P3 bugs |

---

**Start by reading the files in Step 1. Good luck!** 🚀
