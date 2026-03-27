# eforge Benchmarks

SWE-bench evaluation harness for [eforge](https://github.com/eforge-build/eforge).

Tests whether eforge's multi-agent pipeline (plan → build → blind review → evaluate) produces higher-quality patches than vanilla Claude on real GitHub issues.

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
# Smoke test: 5 instances, eforge only
python harness/run_benchmark.py --instances 5

# With evaluation (runs patches through SWE-bench Docker harness)
python harness/run_benchmark.py --instances 5 --eval

# Compare eforge vs vanilla Claude
python harness/run_benchmark.py --instances 10 --baseline --eval

# Specific instances
python harness/run_benchmark.py --instance-ids "astropy__astropy-12907,django__django-11179"
```

## Results

Each run creates a timestamped directory in `results/`:

```
results/2026-03-27T12-00-00/
  config.json                  # Run configuration
  eforge_predictions.jsonl     # Patches in SWE-bench format
  eforge_metadata.jsonl        # Full run data (timing, logs)
  claude-baseline_predictions.jsonl  # (if --baseline)
  claude-baseline_metadata.jsonl
```

Compare results:

```bash
python analysis/compare.py results/<timestamp>/
```

## Methodology

For each SWE-bench instance:

1. Clone the repository at the pre-fix commit (`base_commit`)
2. Write the `problem_statement` as a PRD file
3. Run `eforge build --foreground --auto --no-monitor --no-plugins`
4. Capture the resulting `git diff` as the patch prediction
5. (Optional) Run the SWE-bench evaluation harness to check if tests pass

The baseline runs `claude --print` with the same problem statement for comparison.

## Notes

- **Start with SWE-bench Lite** (300 instances) — smaller, faster iteration
- **Avoid SWE-bench Verified** — contaminated as of Feb 2026
- **For publishable results**, use SWE-bench Pro (731 public instances)
- **Cost estimate**: ~$10-30 per instance for eforge (multi-agent pipeline), ~$2-5 for baseline
- **The key metric**: resolution rate delta between eforge and baseline
