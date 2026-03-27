# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

SWE-bench evaluation harness for **eforge**. Tests whether eforge's multi-agent pipeline produces higher-quality patches than vanilla Claude on real GitHub issues. Runs eforge inside SWE-bench Docker containers (correct Python environment per instance), captures git diffs, and optionally evaluates them through the SWE-bench harness.

## Setup

```bash
chmod +x setup.sh && ./setup.sh
source .venv/bin/activate
```

Prerequisites: Docker, Python 3.11+, Node.js 18+, `eforge` installed globally.

## Running Benchmarks

```bash
# Activate venv first
source .venv/bin/activate

# Curated 5-instance starter set (Docker mode, recommended)
python harness/run_benchmark.py --starter

# With SWE-bench evaluation
python harness/run_benchmark.py --starter --eval

# With vanilla Claude baseline for A/B comparison
python harness/run_benchmark.py --starter --baseline --eval

# Specific instances
python harness/run_benchmark.py --instance-ids "pytest-dev__pytest-5227,sphinx-doc__sphinx-8273"

# First N from dataset
python harness/run_benchmark.py --instances 20

# Host mode (no Docker — not recommended, wrong Python env)
python harness/run_benchmark.py --starter --no-docker

# Compare results from a run
python analysis/compare.py results/<timestamp>/
```

Key flags: `--timeout <seconds>` (default 900), `--skip-eforge` (baseline only), `--dataset <name>`.

## Architecture

**Two execution modes:**
- **Docker (default):** For each instance, builds an eforge layer (`Dockerfile.eforge`) on top of the SWE-bench base image (which has the correct Python + deps). The container runs `harness/entrypoint.sh` which checks out the base commit, runs `eforge build`, and captures the diff.
- **Host (`--no-docker`):** Clones repos into `repos/`, runs eforge directly. Faster but eforge's self-validation may fail due to missing Python packages.

**Key files:**
- `harness/run_benchmark.py` — Main orchestrator: loads SWE-bench dataset, manages Docker images, runs eforge/baseline, saves results
- `harness/entrypoint.sh` — Docker container entrypoint: resets repo, runs eforge, captures patch
- `Dockerfile.eforge` — Layers Node.js 24.x + eforge onto SWE-bench base images
- `analysis/compare.py` — Side-by-side comparison of eforge vs baseline results

**Data flow:** SWE-bench instance → PRD (issue.md) + eforge.yaml written to temp dir → mounted into Docker container → eforge produces patch → diff extracted and filtered (benchmark artifacts removed) → saved as JSONL in `results/<timestamp>/`

## Auth

Authentication is resolved in order: `ANTHROPIC_API_KEY` env var (can be set in `.env`), then `~/.claude/` and `~/.claude.json` mounted read-only into the container.

## Docker Image Naming

SWE-bench images: `swebench/sweb.eval.x86_64.<id>:latest` where `__` in instance IDs becomes `_1776_`. Eforge layer images: `eforge-bench/<instance_id>:latest`. Set `EFORGE_BENCH_REBUILD=1` to force rebuild.

## Results

Timestamped directories under `results/` containing:
- `config.json` — run configuration
- `eforge_predictions.jsonl` / `eforge_metadata.jsonl` — patches + full run data
- `claude-baseline_predictions.jsonl` / `claude-baseline_metadata.jsonl` (if `--baseline`)

## Notes

- Dataset is `princeton-nlp/SWE-bench_Lite` by default. Avoid SWE-bench Verified (contaminated).
- Cost: ~$10-30/instance for eforge, ~$2-5 for baseline.
- Repos are cached in `repos/` across runs.
- The `filter_benchmark_artifacts()` function strips diffs for `eforge.yaml`, `docs/swe-bench-issue.md`, and `.eforge/` from patches.
