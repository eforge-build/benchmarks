# eforge Benchmarks

SWE-bench evaluation harness for [eforge](https://github.com/eforge-build/eforge).

Tests whether eforge's multi-agent pipeline (plan, build, blind review, evaluate) produces higher-quality patches than vanilla Claude on real GitHub issues.

## Prerequisites

- Linux x86_64 (SWE-bench Docker images are x86_64 only)
- Docker
- Python 3.11+
- Node.js 18+
- `eforge` installed globally (`npm install -g eforge`)
- Anthropic API key or Claude Max subscription

## Setup

```bash
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
```

## Quick Start

```bash
# Curated 5-instance starter set (runs in Docker by default)
python harness/run_benchmark.py --starter

# Starter set + evaluate patches through SWE-bench Docker harness
python harness/run_benchmark.py --starter --eval

# Compare eforge vs vanilla Claude
python harness/run_benchmark.py --starter --baseline --eval

# Specific instances
python harness/run_benchmark.py --instance-ids "pytest-dev__pytest-5227,sphinx-doc__sphinx-8273"

# First N from dataset (less targeted)
python harness/run_benchmark.py --instances 20

# Run on host without Docker (not recommended — wrong Python environment)
python harness/run_benchmark.py --starter --no-docker
```

## Starter Instances

The `--starter` flag uses a curated set of 5 instances selected for:
- Medium difficulty (40-70% solve rate across top agents)
- Clear problem statements
- Manageable repo sizes (not Django's 400K+ lines)
- Variety across repos (scikit-learn, pytest, sphinx)

| Instance | Repo | Rationale |
|---|---|---|
| `scikit-learn__scikit-learn-10870` | scikit-learn | Known medium difficulty, clear logic bug |
| `scikit-learn__scikit-learn-13241` | scikit-learn | Clear API issue |
| `pytest-dev__pytest-5103` | pytest | Bug report with reproduction steps |
| `pytest-dev__pytest-5227` | pytest | Well-scoped fixture issue |
| `sphinx-doc__sphinx-8273` | sphinx | Lower solve rate (37%), tests methodology value |

## How It Works

By default, eforge runs inside SWE-bench Docker containers with the correct Python environment. This lets eforge's validation-fix cycle work properly (it can actually run the project's tests).

For each SWE-bench instance:

1. **Build Docker image** — SWE-bench base image (correct Python + deps) + Node.js + eforge layer
2. **Start container** with Claude auth mounted from `~/.claude/`
3. **Checkout** `base_commit` (pre-fix state)
4. **Run** `eforge build --foreground --auto --no-monitor --no-plugins`
5. **Extract** the resulting `git diff`, filtering out benchmark artifacts
6. **(Optional)** Run SWE-bench evaluation harness to verify tests pass

The `--no-docker` flag falls back to running on the host (faster, but wrong Python environment means eforge's self-validation may fail on missing packages).

The baseline runs `claude --print` with the same problem statement for A/B comparison.

## Results

Each run creates a timestamped directory in `results/`:

```
results/2026-03-27T18-00-00/
  config.json                        # Run configuration
  eforge_predictions.jsonl           # Patches in SWE-bench format
  eforge_metadata.jsonl              # Full run data (timing, exit codes, logs)
  claude-baseline_predictions.jsonl  # (if --baseline)
  claude-baseline_metadata.jsonl
```

Compare results:

```bash
python analysis/compare.py results/<timestamp>/
```

## Notes

- **Timeout default is 15 minutes** per instance. eforge's multi-agent pipeline is slower than single-pass agents. Override with `--timeout 1200` if needed.
- **Repos are cached** in `repos/` and reused across runs (shared by instance from the same repo). First run is slow due to cloning.
- **Avoid SWE-bench Verified** — contaminated as of Feb 2026. Use Lite (default) or Pro for honest results.
- **Cost estimate**: ~$10-30 per instance for eforge (multi-agent pipeline), ~$2-5 for baseline.
- **The key metric**: resolution rate delta between eforge and baseline on the same instances.
