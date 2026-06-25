#!/usr/bin/env bash
# Run 3 full wifi_llapi test runs sequentially and log results.

cd "$(dirname "$0")/.."

FW_VER="${1:-4.0.3}"
LOG_DIR="/tmp/testpilot_3x_runs"
mkdir -p "$LOG_DIR"

SUMMARY_FILE="$LOG_DIR/summary.json"
echo '{"runs":[]}' > "$SUMMARY_FILE"

for RUN_NUM in 1 2 3; do
    LOG_FILE="$LOG_DIR/run${RUN_NUM}.log"
    echo "=== Run $RUN_NUM started at $(date -Iseconds) ===" | tee -a "$LOG_FILE"

    START_TS=$(date +%s)
    uv run python -m testpilot.cli run wifi_llapi --dut-fw-ver "$FW_VER" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    END_TS=$(date +%s)
    ELAPSED=$(( END_TS - START_TS ))

    echo "=== Run $RUN_NUM finished at $(date -Iseconds) (${ELAPSED}s, exit=$EXIT_CODE) ===" | tee -a "$LOG_FILE"

    # Extract run_id from the log (last run_id line)
    RUN_ID=$(grep -oP "'run_id':\s*'[^']+'" "$LOG_FILE" | tail -1 | grep -oP "'[^']+'" | tail -1 | tr -d "'") || true

    # Append to summary
    python3 -c "
import json, sys
with open('$SUMMARY_FILE') as f:
    s = json.load(f)
s['runs'].append({
    'run_num': $RUN_NUM,
    'run_id': '${RUN_ID:-unknown}',
    'exit_code': $EXIT_CODE,
    'elapsed_seconds': $ELAPSED,
    'log_file': '$LOG_FILE',
})
with open('$SUMMARY_FILE', 'w') as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
"
    echo "Run $RUN_NUM run_id=${RUN_ID:-unknown} elapsed=${ELAPSED}s exit=$EXIT_CODE"

    # Recover serialwrap sessions between runs to avoid ATTACHED state
    if [ "$RUN_NUM" -lt 3 ]; then
        echo "Recovering serialwrap sessions before next run..."
        serialwrap session attach --selector COM0 2>/dev/null || true
        serialwrap session attach --selector COM1 2>/dev/null || true
        sleep 5
    fi
done

echo ""
echo "=== All 3 runs complete. Summary: $SUMMARY_FILE ==="
cat "$SUMMARY_FILE"
