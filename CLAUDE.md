# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

SWE-bench evaluation harness for **eforge**. Runs eforge inside SWE-bench Docker containers (with the correct Python environment per instance), captures git diffs, and evaluates them through the SWE-bench harness. Also supports A/B comparison against vanilla Claude.

## Setup

```bash
chmod +x setup.sh && ./setup.sh
source .venv/bin/activate
source .env  # must export ANTHROPIC_API_KEY
```

Prerequisites: Docker, Python 3.11+, Node.js 18+.

## Running Benchmarks

```bash
# Curated 5-instance starter set with evaluation
python harness/run_benchmark.py --starter --eval

# Force rebuild Docker images (after eforge update)
EFORGE_BENCH_REBUILD=1 python harness/run_benchmark.py --starter --eval

# With vanilla Claude baseline for A/B comparison
python harness/run_benchmark.py --starter --baseline --eval

# Specific instances
python harness/run_benchmark.py --instance-ids "pytest-dev__pytest-5227,sphinx-doc__sphinx-8273"

# Compare results
python analysis/compare.py results/<timestamp>/
```

Key flags: `--timeout <seconds>` (default 900), `--skip-eforge` (baseline only), `--dataset <name>`, `--no-docker` (host mode, not recommended).

## Architecture

**Key files:**
- `harness/run_benchmark.py` -- Main orchestrator: loads SWE-bench dataset, manages Docker images, runs eforge/baseline, saves results
- `harness/entrypoint.sh` -- Docker container entrypoint: resets repo to base commit, runs eforge, captures patch diff
- `Dockerfile.eforge` -- Layers Node.js 24.x + Claude Code CLI + eforge onto SWE-bench base images
- `analysis/compare.py` -- Side-by-side comparison of eforge vs baseline results

**Data flow:** SWE-bench instance -> PRD (issue.md) + eforge/config.yaml written to temp dir -> mounted into Docker container at /input -> eforge produces patch -> diff extracted against baseline commit and filtered (benchmark artifacts removed) -> saved as JSONL in `results/<timestamp>/`

**Docker container setup:**
- Runs as non-root `eforge` user (Claude Code refuses `bypassPermissions` as root)
- Claude Code installed via `curl -fsSL https://claude.ai/install.sh | bash` (not npm)
- Claude Code binary lives at `/home/eforge/.local/bin/claude`
- Auth via `ANTHROPIC_API_KEY` env var passed to container
- Monitor port pinned to 4567 via `EFORGE_MONITOR_PORT=4567` env var, mapped to host port 4566 (`-p 4566:4567`)
- Entrypoint auto-detects default branch (some repos use `master`, not `main`)

## Docker Image Naming

SWE-bench images: `swebench/sweb.eval.x86_64.<id>:latest` where `__` in instance IDs becomes `_1776_`. Eforge layer images: `eforge-bench/<instance_id>:latest`. Set `EFORGE_BENCH_REBUILD=1` env var to force rebuild.

## Results and Evaluation

Timestamped directories under `results/` containing:
- `config.json` -- run configuration
- `eforge_predictions.jsonl` / `eforge_metadata.jsonl` -- patches + full run data
- `claude-baseline_predictions.jsonl` / `claude-baseline_metadata.jsonl` (if `--baseline`)

Evaluation logs go to `logs/run_evaluation/<run_id>/<model>/<instance_id>/`:
- `run_instance.log` -- container setup, patch application, grading
- `test_output.txt` -- raw test output
- `report.json` -- pass/fail per test, resolved status
- `patch.diff` -- the patch as applied

The `filter_benchmark_artifacts()` function strips diffs for `eforge/`, `docs/swe-bench-issue.md`, and `.eforge/` from patches before saving predictions.

## Known Issues

- **Dataset**: `princeton-nlp/SWE-bench_Lite` by default. Avoid SWE-bench Verified (contaminated as of Feb 2026).
- **Cost**: ~$10-30/instance for eforge (multi-agent pipeline), ~$2-5 for baseline.
- **Repos cached** in `repos/` across runs (host mode only).
- **pytest-dev__pytest-5103** consistently hits the planner's max turns limit -- it's a complex AST rewriting task.
