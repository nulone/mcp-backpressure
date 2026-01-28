# Resume Prompt: mcp-backpressure

> Use this prompt to continue after a context checkpoint or interrupted session

---

## Your Mission

**RESUME** implementation of **mcp-backpressure** — Backpressure/concurrency control middleware for FastMCP MCP servers

This is a **continuation** session. Previous work exists.

---

## Step 1: Restore State (CRITICAL)

```bash
# Check what exists
ls -la src/mcp_backpressure/
ls -la tests/

# Read current state
cat .agent/STATE.md
```

**Parse STATE.md carefully:**
- What tasks are ✅ completed?
- What task was 🔄 in progress?
- What tasks are ⬜ remaining?
- Any blockers or notes?

---

## Step 2: Verify Existing Work

```bash
# Run existing tests
source .venv/bin/activate
pytest tests/ -v

# Check lint
ruff check src/ tests/
```

**Do NOT rewrite working code!** Only continue from where stopped.

---

## Step 3: Continue Implementation

Resume from the **in progress** task in STATE.md.

Remember:
1. Write test first (TDD)
2. Implement to pass test
3. Mark task complete in STATE.md
4. **Monitor context — checkpoint at 60% again!**

---

## Step 4: Validate & Complete

When all tasks done:

```bash
pytest tests/ -v
ruff check src/ tests/
mcp-backpressure --help
```

Update AGENT_LOG.md with session summary.

---

## ⚠️ Context Management

This is session 1 (or later).

**Still monitor context!** If you approach 60% again:
1. STOP and update STATE.md
2. Commit checkpoint
3. Output checkpoint message
4. Wait for next session

---

## Anti-Patterns (DO NOT DO)

❌ Rewriting existing working code
❌ Ignoring STATE.md progress markers  
❌ Starting from scratch
❌ Skipping test verification
❌ Ignoring context limits

---

## Quick Reference

| File | Action |
|------|--------|
| `.agent/STATE.md` | **READ FIRST** — shows progress |
| `.agent/PLAN.md` | Full task list |
| `.agent/AGENTS.md` | Rules and validation |
| `BUGS.md` | Known issues |
| `src/` | **CHECK EXISTING CODE** |
| `tests/` | **RUN EXISTING TESTS** |

---

**Start by reading STATE.md to understand current progress!**
