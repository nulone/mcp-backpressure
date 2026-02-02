# BUGS

## P1 (Critical) — Must fix immediately

_None yet_

## P2 (Important) — Fix before release

_None yet_

## P3 (Nice-to-have) — Backlog

_None yet_

---

## Statistics
- Total found: 0
- P1 fixed: 0/0
- P2 documented: 0
- P3 documented: 0

---

## Template for Bugs

When bugs are found, document them like this:

### BUG-XXX: [Title]
- **Found by:** [codex basic | codex adversarial | gemini basic | gemini adversarial]
- **File:** path/to/file.py:XX-YY
- **Problem:** Description of the issue
- **Impact:** What breaks or goes wrong
- **Fix:** How to fix it

## Known Issues (v0.1.0)

### P2: Potential permit leak on exception between wait_for and try block
- Location: middleware.py:202-207
- Impact: Very narrow window, low probability
- Fix planned: v0.1.1
