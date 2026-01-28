#!/usr/bin/env bash
# =============================================================================
# FRESH EYES RUNNER - Run FE-01..FE-05 via Claude CLI
# Usage: ./fresh-eyes.sh [project_dir] [output_dir]
# =============================================================================

set -e

PROJECT_DIR="${1:-.}"
OUTPUT_DIR="${2:-./fresh-eyes-reports}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$OUTPUT_DIR"

echo "🔍 Fresh Eyes Runner"
echo "   Project: $PROJECT_DIR"
echo "   Output:  $OUTPUT_DIR"
echo ""

# -----------------------------------------------------------------------------
# Collect code for review
# -----------------------------------------------------------------------------
collect_code() {
    echo "📦 Collecting code..."
    
    CODE=""
    
    # Core files
    for f in "$PROJECT_DIR"/src/mcp_backpressure/*.py; do
        if [ -f "$f" ]; then
            CODE+="
### $(basename $f)
\`\`\`python
$(cat "$f")
\`\`\`
"
        fi
    done
    
    # Test files
    for f in "$PROJECT_DIR"/tests/*.py; do
        if [ -f "$f" ]; then
            CODE+="
### $(basename $f)
\`\`\`python
$(cat "$f")
\`\`\`
"
        fi
    done
    
    # README
    if [ -f "$PROJECT_DIR/README.md" ]; then
        CODE+="
### README.md
$(cat "$PROJECT_DIR/README.md")
"
    fi
    
    echo "$CODE"
}

# -----------------------------------------------------------------------------
# JSON Schema for all reports
# -----------------------------------------------------------------------------
JSON_SCHEMA='{
  "task_id": "FE-XX",
  "score": 0,
  "summary": "string",
  "release_blockers": [
    {
      "severity": "high|medium",
      "description": "string",
      "location": "file.py:line",
      "evidence": "why this is a problem",
      "test_to_add": "string"
    }
  ],
  "warnings": [
    {
      "severity": "low",
      "description": "string",
      "location": "string"
    }
  ],
  "scope_creep": ["string"],
  "praise": ["string"],
  "must_fix_for_release": ["string"]
}'

# -----------------------------------------------------------------------------
# Task Prompts
# -----------------------------------------------------------------------------

FE_01_PROMPT='You are reviewing a FastMCP backpressure middleware.

**FOCUS**: Core correctness under concurrency.

**INVARIANTS TO VERIFY**:
1. `active <= max_concurrent` ALWAYS
2. `queued <= queue_size` ALWAYS  
3. Cancel while queued → slot freed (no permit leak)
4. Cancel while active → counter decremented
5. After burst → active=0, queued=0

**LOOK FOR**:
- Double release of semaphore permits
- Missing release on exception/cancel paths
- Deadlocks when cancel + lock interact
- "Lost wakeup" where queued item never proceeds

**RULES**:
- NO refactors or new features
- Every blocker MUST include test idea
- Diff should be <30 LOC per fix

Return JSON only. task_id = "FE-01"'

FE_02_PROMPT='You are reviewing timeout and error handling in a backpressure middleware.

**FOCUS**: Timeout semantics + JSON-RPC error contract.

**TIMEOUT CHECKS**:
- Uses monotonic time (not wall clock)
- Timeout removes item from queue (no leak)
- Timeout does not execute tool (clean reject)

**ERROR CONTRACT CHECKS**:
- `code` always -32001
- `message` stable like "SERVER_OVERLOADED"
- `data` contains: reason, active, queued, max_concurrent, queue_size
- `data.reason` in: queue_full | queue_timeout | concurrency_limit
- No stack traces or internal objects leak
- Error is JSON-serializable

Return JSON only. task_id = "FE-02"'

FE_03_PROMPT='You are an adversarial reviewer trying to exhaust resources despite backpressure.

**FOCUS**: Does backpressure actually work?

**ATTACK VECTORS**:
1. 10,000 requests in 1 second → memory grows unbounded?
2. Queue items hold large closures → memory leak?
3. Each queued item creates background task → task explosion?
4. O(n) operations on queue length → CPU exhaustion?
5. Slow timeout cleanup → queue grows despite limit?

**LOOK FOR**:
- Lists/dicts that grow per request without cleanup
- Tasks created but not tracked/cancelled
- Heavy objects retained in queue
- Paths that bypass queue_size limit

Return JSON only. task_id = "FE-03"'

FE_04_PROMPT='You are reviewing transport assumptions in FastMCP middleware.

**CONTEXT**: Middleware may run under stdio or HTTP.

**CHECK FOR**:
- Core logic transport-agnostic
- No "if http then..." in middleware.py
- Cancellation works regardless of transport
- Error payload works for both

**SMOKE TEST PLAN** (just describe, dont implement):
1. STDIO: burst 10 requests, verify limits
2. HTTP: same test

Return JSON only. task_id = "FE-04"'

FE_05_PROMPT='You are reviewing developer experience for OSS release.

**FOCUS**: Can a developer use this in 5 minutes?

**README CHECKLIST**:
- [ ] Quickstart ≤10 lines
- [ ] All parameters documented
- [ ] Example of overload error payload
- [ ] "Rate limiting ≠ concurrency" explanation

**EXAMPLES CHECKLIST**:
- [ ] simple_server.py runs
- [ ] load_simulation.py shows metrics

Return JSON only. task_id = "FE-05"'

# -----------------------------------------------------------------------------
# Run single task
# -----------------------------------------------------------------------------
run_task() {
    local task_id="$1"
    local prompt="$2"
    local code="$3"
    local output_file="$OUTPUT_DIR/${task_id}_${TIMESTAMP}.json"
    
    echo "🔍 Running $task_id..."
    
    local full_prompt="$prompt

JSON Schema for response:
$JSON_SCHEMA

Code to review:
$code"
    
    # Run via Claude CLI
    # Adjust command based on your Claude CLI setup
    if command -v claude &> /dev/null; then
        echo "$full_prompt" | claude --output-format json > "$output_file" 2>/dev/null || {
            # Fallback: just save prompt for manual run
            echo "⚠️  Claude CLI failed, saving prompt to $output_file.prompt"
            echo "$full_prompt" > "$output_file.prompt"
            return 1
        }
    else
        echo "⚠️  Claude CLI not found, saving prompt to $output_file.prompt"
        echo "$full_prompt" > "$output_file.prompt"
        return 1
    fi
    
    echo "   ✅ Saved to $output_file"
}

# -----------------------------------------------------------------------------
# Aggregate results
# -----------------------------------------------------------------------------
aggregate() {
    echo ""
    echo "📊 Aggregating results..."
    
    local summary_file="$OUTPUT_DIR/summary_${TIMESTAMP}.json"
    
    python3 << EOF
import json
import glob
import os

reports = []
for f in glob.glob("$OUTPUT_DIR/FE-*_$TIMESTAMP.json"):
    try:
        with open(f) as fp:
            reports.append(json.load(fp))
    except:
        pass

if not reports:
    print("No valid reports found")
    exit(0)

# Calculate summary
scores = [r.get("score", 0) for r in reports]
avg_score = sum(scores) / len(scores) if scores else 0

all_blockers = []
for r in reports:
    for b in r.get("release_blockers", []):
        b["from_task"] = r.get("task_id", "?")
        all_blockers.append(b)

high_blockers = [b for b in all_blockers if b.get("severity") == "high"]
medium_blockers = [b for b in all_blockers if b.get("severity") == "medium"]

# Determine recommendation
if avg_score >= 8 and not high_blockers:
    recommendation = "ship"
elif avg_score >= 6 and len(high_blockers) <= 2:
    recommendation = "fix_and_rerun"
else:
    recommendation = "major_rework"

summary = {
    "timestamp": "$TIMESTAMP",
    "tasks_run": len(reports),
    "average_score": round(avg_score, 1),
    "high_blockers": len(high_blockers),
    "medium_blockers": len(medium_blockers),
    "release_ready": avg_score >= 6 and not high_blockers,
    "recommendation": recommendation,
    "blockers": all_blockers[:10],  # Top 10
    "task_scores": {r.get("task_id"): r.get("score") for r in reports}
}

with open("$summary_file", "w") as fp:
    json.dump(summary, fp, indent=2)

print(f"   Average score: {avg_score:.1f}/10")
print(f"   High blockers: {len(high_blockers)}")
print(f"   Medium blockers: {len(medium_blockers)}")
print(f"   Recommendation: {recommendation}")
print(f"   Summary: $summary_file")
EOF
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    CODE=$(collect_code)
    
    if [ -z "$CODE" ]; then
        echo "❌ No code found in $PROJECT_DIR"
        exit 1
    fi
    
    echo "📝 Code collected ($(echo "$CODE" | wc -l) lines)"
    echo ""
    
    run_task "FE-01" "$FE_01_PROMPT" "$CODE"
    run_task "FE-02" "$FE_02_PROMPT" "$CODE"
    run_task "FE-03" "$FE_03_PROMPT" "$CODE"
    run_task "FE-04" "$FE_04_PROMPT" "$CODE"
    run_task "FE-05" "$FE_05_PROMPT" "$CODE"
    
    aggregate
    
    echo ""
    echo "✅ Fresh Eyes complete!"
    echo "   Reports: $OUTPUT_DIR/"
}

main
