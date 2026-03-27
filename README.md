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
# Curated 5-instance starter set (recommended first run)
python harness/run_benchmark.py --starter

# Starter set + evaluate patches through SWE-bench Docker harness
python harness/run_benchmark.py --starter --eval

# Compare eforge vs vanilla Claude
python harness/run_benchmark.py --starter --baseline --eval

# Specific instances
python harness/run_benchmark.py --instance-ids "scikit-learn__scikit-learn-10870,pytest-dev__pytest-5103"

# First N from dataset (less targeted)
python harness/run_benchmark.py --instances 20
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

For each SWE-bench instance:

1. **Clone** the repository at the pre-fix commit (`base_commit`)
2. **Write `eforge.yaml`** with empty validation (SWE-bench handles test evaluation in Docker, not eforge)
3. **Write PRD** from the `problem_statement` (GitHub issue text)
4. **Run** `eforge build --foreground --auto --no-monitor --no-plugins`
5. **Capture** the resulting `git diff`, filtering out benchmark artifacts (PRD, eforge.yaml)
6. **(Optional)** Run SWE-bench evaluation harness to check if tests pass

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
