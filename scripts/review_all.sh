#!/bin/bash
# Full validation pipeline
# Usage: ./review_all.sh [project_dir]

set -euo pipefail

PROJECT_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   FULL VALIDATION PIPELINE            ║${NC}"
echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo ""

# Counter for failures
FAILURES=0

# Validate PROJECT_DIR to prevent shell injection (P1 security fix)
# Only allow alphanumeric, hyphens, underscores, dots, and forward slashes
if [[ ! "$PROJECT_DIR" =~ ^[a-zA-Z0-9._/-]+$ ]]; then
    echo -e "${RED}Error: Invalid PROJECT_DIR path${NC}"
    echo "PROJECT_DIR contains potentially dangerous characters"
    echo "Allowed: alphanumeric, dots, hyphens, underscores, forward slashes"
    exit 1
fi

run_check() {
    local name="$1"
    local cmd="$2"

    echo -e "${BLUE}▶ Running: $name${NC}"
    if eval "$cmd"; then
        echo -e "${GREEN}✓ $name passed${NC}\n"
    else
        echo -e "${RED}✗ $name failed${NC}\n"
        ((FAILURES++))
    fi
}

# 1. Pytest
run_check "pytest" "\"$PROJECT_DIR\"/.venv/bin/python -m pytest \"$PROJECT_DIR\"/tests/ -v"

# 2. Ruff
run_check "ruff" "\"$PROJECT_DIR\"/.venv/bin/ruff check \"$PROJECT_DIR\"/src/ \"$PROJECT_DIR\"/tests/"

# 3. Codex basic
if command -v codex &> /dev/null; then
    run_check "codex (basic)" "cd \"$PROJECT_DIR\" && codex review --uncommitted"
else
    echo -e "${YELLOW}⚠ codex not found, skipping basic review${NC}\n"
fi

# 4. Codex adversarial
if command -v codex &> /dev/null; then
    run_check "codex (adversarial)" "cd \"$PROJECT_DIR\" && codex review 'QA adversarial: try to BREAK. P1/P2/P3.'"
else
    echo -e "${YELLOW}⚠ codex not found, skipping adversarial review${NC}\n"
fi

# 5. Gemini basic
if [[ -f "$SCRIPT_DIR/gemini_review.sh" ]] && [[ -n "${NANOGPT_API_KEY:-}" ]]; then
    run_check "gemini (basic)" "\"$SCRIPT_DIR\"/gemini_review.sh basic \"$PROJECT_DIR\""
else
    echo -e "${YELLOW}⚠ gemini_review.sh not found or NANOGPT_API_KEY not set${NC}\n"
fi

# 6. Gemini adversarial
if [[ -f "$SCRIPT_DIR/gemini_review.sh" ]] && [[ -n "${NANOGPT_API_KEY:-}" ]]; then
    run_check "gemini (adversarial)" "\"$SCRIPT_DIR\"/gemini_review.sh adversarial \"$PROJECT_DIR\""
else
    echo -e "${YELLOW}⚠ gemini_review.sh not found or NANOGPT_API_KEY not set${NC}\n"
fi

# Summary
echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   VALIDATION SUMMARY                   ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"

if [[ $FAILURES -eq 0 ]]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo -e "${YELLOW}⚠ Remember: Tests pass ≠ No bugs${NC}"
    echo -e "${YELLOW}⚠ Review output above for P1/P2/P3 issues${NC}"
    exit 0
else
    echo -e "${RED}✗ $FAILURES check(s) failed${NC}"
    exit 1
fi
