#!/bin/bash
set -euo pipefail

BASE_COMMIT="${BASE_COMMIT:?BASE_COMMIT env var required}"
TIMEOUT="${TIMEOUT:-900}"

# Ignore SIGPIPE — Node.js (eforge) doesn't handle it, and in Docker
# redirected I/O can trigger it during process exit, causing exit code 13.
trap '' PIPE

cd /testbed

# Reset to pre-fix state on the default branch
DEFAULT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || git branch --list main master | head -1 | tr -d ' ')
git checkout -f "$DEFAULT_BRANCH" 2>/dev/null
git reset --hard "$BASE_COMMIT" 2>/dev/null
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
timeout --preserve-status "$TIMEOUT" eforge build /input/issue.md \
    --foreground --auto --no-plugins \
    > /output/stdout.log 2> /output/stderr.log
EXIT_CODE=$?
set -e

# Capture the full diff from baseline
git add -A
git diff --cached "$BASELINE_SHA" > /output/raw_patch.diff

echo "$EXIT_CODE" > /output/exit_code
echo "eforge finished with exit code $EXIT_CODE"
