#!/bin/bash
set -euo pipefail

BASE_COMMIT="${BASE_COMMIT:?BASE_COMMIT env var required}"
TIMEOUT="${TIMEOUT:-900}"

cd /testbed

# Reset to pre-fix state
git checkout -f "$BASE_COMMIT" 2>/dev/null
git clean -fdx 2>/dev/null

# Copy eforge config into repo
if [ -f /input/eforge.yaml ]; then
    cp /input/eforge.yaml .
fi

# Commit baseline for clean diffing
git add -A
git commit -m "benchmark baseline" --allow-empty -q

BASELINE_SHA=$(git rev-parse HEAD)

# Run eforge with timeout
# timeout returns 124 on timeout, eforge may return non-zero on failure
set +e
timeout "$TIMEOUT" eforge build /input/issue.md \
    --foreground --auto --no-monitor --no-plugins \
    > /output/stdout.log 2> /output/stderr.log
EXIT_CODE=$?
set -e

# Capture the full diff from baseline
git add -A
git diff --cached "$BASELINE_SHA" > /output/raw_patch.diff

echo "$EXIT_CODE" > /output/exit_code
echo "eforge finished with exit code $EXIT_CODE"
