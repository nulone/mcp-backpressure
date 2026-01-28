#!/bin/bash
# Gemini API code review script
# Usage: ./gemini_review.sh [basic|adversarial|compliance] [project_dir]
# Requires: NANOGPT_API_KEY environment variable

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-basic}"
PROJECT_DIR="${2:-.}"
MODEL="gemini-3-flash-preview-thinking"
API_URL="https://api.nano-gpt.com/v1/chat/completions"
TIMEOUT=120
MAX_RETRIES=3

# Validate PROJECT_DIR to prevent shell injection (P1 security fix)
# Only allow alphanumeric, hyphens, underscores, dots, and forward slashes
if [[ ! "$PROJECT_DIR" =~ ^[a-zA-Z0-9._/-]+$ ]]; then
    echo -e "${RED}Error: Invalid PROJECT_DIR path${NC}"
    echo "PROJECT_DIR contains potentially dangerous characters"
    echo "Allowed: alphanumeric, dots, hyphens, underscores, forward slashes"
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check API key
if [[ -z "${NANOGPT_API_KEY:-}" ]]; then
    echo -e "${RED}Error: NANOGPT_API_KEY not set${NC}"
    echo "Add to ~/.zshrc: export NANOGPT_API_KEY=\"your-key\""
    exit 1
fi

# Prompts
case "$MODE" in
    basic)
        PROMPT="Review this Python codebase for bugs, errors, and issues. Categorize findings as P1 (critical), P2 (important), or P3 (nice-to-have)."
        ;;
    adversarial)
        PROMPT="You are a QA engineer trying to BREAK this code. Find edge cases, crashes, wrong results, security issues. What inputs cause problems? Categorize as P1/P2/P3."
        ;;
    compliance)
        PROMPT="Review this code for: 1) Security vulnerabilities (OWASP top 10), 2) Type safety issues, 3) Error handling gaps, 4) Resource leaks. Categorize as P1/P2/P3."
        ;;
    *)
        echo -e "${RED}Invalid mode: $MODE${NC}"
        echo "Usage: $0 [basic|adversarial|compliance] [project_dir]"
        exit 1
        ;;
esac

echo -e "${BLUE}=== Gemini Review ($MODE) ===${NC}"
echo -e "Model: $MODEL"
echo -e "Directory: $PROJECT_DIR\n"

# Collect code
CODE=$(find "$PROJECT_DIR/src" -name "*.py" -type f 2>/dev/null | while read file; do
    echo "# File: $file"
    cat "$file"
    echo ""
done)

if [[ -z "$CODE" ]]; then
    echo -e "${YELLOW}No Python files found in $PROJECT_DIR/src${NC}"
    exit 0
fi

# Build request
REQUEST=$(cat <<EOF
{
  "model": "$MODEL",
  "messages": [
    {"role": "user", "content": "$PROMPT\n\n$CODE"}
  ],
  "temperature": 0.3
}
EOF
)

# Spinner animation
spin() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while kill -0 "$pid" 2>/dev/null; do
        local temp=${spinstr#?}
        printf " [%c] Waiting for Gemini..." "$spinstr"
        spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\r"
    done
    printf "    \r"
}

# Make request with retries
for attempt in $(seq 1 $MAX_RETRIES); do
    echo -e "${BLUE}Sending request (attempt $attempt/$MAX_RETRIES)...${NC}"

    RESPONSE=$(mktemp)
    curl -s -X POST "$API_URL" \
        -H "Authorization: Bearer $NANOGPT_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$REQUEST" \
        --max-time $TIMEOUT > "$RESPONSE" 2>&1 &

    CURL_PID=$!
    spin $CURL_PID
    wait $CURL_PID
    CURL_EXIT=$?

    if [[ $CURL_EXIT -eq 0 ]]; then
        # Check for API errors
        if grep -q '"error"' "$RESPONSE"; then
            ERROR_MSG=$(jq -r '.error.message // "Unknown error"' "$RESPONSE" 2>/dev/null || echo "Parse error")
            echo -e "${RED}API Error: $ERROR_MSG${NC}"

            if [[ $attempt -lt $MAX_RETRIES ]]; then
                echo -e "${YELLOW}Retrying in 2 seconds...${NC}"
                sleep 2
                continue
            else
                rm -f "$RESPONSE"
                exit 1
            fi
        fi

        # Success - extract review
        REVIEW=$(jq -r '.choices[0].message.content' "$RESPONSE" 2>/dev/null)
        TOKENS=$(jq -r '.usage.total_tokens // 0' "$RESPONSE" 2>/dev/null)

        if [[ -z "$REVIEW" ]] || [[ "$REVIEW" == "null" ]]; then
            echo -e "${RED}Failed to parse response${NC}"
            rm -f "$RESPONSE"
            exit 1
        fi

        echo -e "${GREEN}✓ Review complete${NC}\n"
        echo "$REVIEW"
        echo ""
        echo -e "${BLUE}Tokens used: $TOKENS${NC}"
        echo -e "${BLUE}Estimated cost: \$$(echo "scale=4; $TOKENS * 0.000001" | bc)${NC}"

        rm -f "$RESPONSE"
        exit 0
    else
        echo -e "${RED}Request failed (timeout or network error)${NC}"
        if [[ $attempt -lt $MAX_RETRIES ]]; then
            echo -e "${YELLOW}Retrying in 2 seconds...${NC}"
            sleep 2
        fi
    fi
done

echo -e "${RED}Failed after $MAX_RETRIES attempts${NC}"
rm -f "$RESPONSE"
exit 1
