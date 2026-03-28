# eforge Benchmarks

SWE-bench evaluation harness for [eforge](https://github.com/eforge-build/eforge).

Tests whether eforge's multi-agent pipeline (plan, build, blind review, evaluate) produces higher-quality patches than vanilla Claude on real GitHub issues.

**[View published results](https://eforge-build.github.io/benchmarks/)**

## Prerequisites

- Docker (SWE-bench images are x86_64; works on ARM Macs via Rosetta)
- Python 3.11+
- Node.js 18+
- Anthropic API key

## Setup

```bash
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
```

Set your API key in `.env`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Then source it before running:

```bash
source .env
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
| `scikit-learn__scikit-learn-10949` | scikit-learn | Known medium difficulty, clear logic bug |
| `scikit-learn__scikit-learn-13241` | scikit-learn | Clear API issue |
| `pytest-dev__pytest-5103` | pytest | Bug report with reproduction steps |
| `pytest-dev__pytest-5227` | pytest | Well-scoped fixture issue |
| `sphinx-doc__sphinx-8273` | sphinx | Lower solve rate (37%), tests methodology value |

## How It Works

By default, eforge runs inside SWE-bench Docker containers with the correct Python environment. This lets eforge's validation-fix cycle work properly (it can actually run the project's tests).

For each SWE-bench instance:

1. **Build Docker image** -- SWE-bench base image (correct Python + deps) + Node.js + Claude Code CLI + eforge layer
2. **Start container** with `ANTHROPIC_API_KEY` passed as env var
3. **Checkout** `base_commit` on the default branch (pre-fix state)
4. **Run** `eforge build --foreground --auto --no-plugins`
5. **Extract** the resulting `git diff`, filtering out benchmark artifacts
6. **(Optional)** Run SWE-bench evaluation harness to verify tests pass

The Docker image runs as a non-root `eforge` user (Claude Code requires non-root for `bypassPermissions` mode). The entrypoint auto-detects the default branch (`main` or `master`).

The `--no-docker` flag falls back to running on the host (faster, but wrong Python environment means eforge's self-validation may fail on missing packages).

The baseline runs `claude --print` with the same problem statement for A/B comparison.

## Monitoring

While a Docker run is in progress, the eforge monitor UI is accessible at **http://localhost:4566**. This lets you watch the planner, builder, and reviewer agents work in real time.

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

SWE-bench evaluation logs are written to `logs/run_evaluation/`.

## Rebuilding Docker Images

Images are cached and reused across runs. To force a rebuild (e.g., after updating eforge):

```bash
EFORGE_BENCH_REBUILD=1 python harness/run_benchmark.py --starter
```

To fully remove cached eforge images:

```bash
docker rmi $(docker images --filter "reference=eforge-bench/*" -q)
```

## Publishing Results

After a benchmark run with `--eval`, publish the results to the [GitHub Pages site](https://eforge-build.github.io/benchmarks/):

```bash
# Clear stale eval cache (required if re-running eval on same instances)
rm -rf logs/run_evaluation/eforge_predictions eforge.eforge_predictions.json

# Publish results from a run
python3 publish.py results/<timestamp>/ --notes "description of this run"

# Review and push
git add docs/ && git commit -m "Publish benchmark results" && git push
```

The publish script merges data from the run config, eforge metadata, and SWE-bench eval report into the site. Each run is appended to the historical record.

## Notes

- **Timeout default is 15 minutes** per instance. eforge's multi-agent pipeline is slower than single-pass agents. Override with `--timeout 1200` if needed.
- **Repos are cached** in `repos/` and reused across runs. First run is slow due to cloning.
- **Avoid SWE-bench Verified** -- contaminated as of Feb 2026. Use Lite (default) or Pro for honest results.
- **Cost estimate**: ~$10-30 per instance for eforge (multi-agent pipeline), ~$2-5 for baseline.
- **The key metric**: resolution rate delta between eforge and baseline on the same instances.
