#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== eforge SWE-bench Benchmark Setup ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Error: docker is required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Error: node is required"; exit 1; }
command -v eforge >/dev/null 2>&1 || { echo "Error: eforge is required (npm install -g eforge)"; exit 1; }

# Create venv and install Python deps
if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
  echo "Creating Python venv..."
  python3 -m venv "$SCRIPT_DIR/.venv"
fi

echo "Installing Python dependencies..."
source "$SCRIPT_DIR/.venv/bin/activate"
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Create working directories
mkdir -p "$SCRIPT_DIR/repos"
mkdir -p "$SCRIPT_DIR/results"

echo ""
echo "Setup complete. To run:"
echo "  source .venv/bin/activate"
echo "  python harness/run_benchmark.py --instances 5"
