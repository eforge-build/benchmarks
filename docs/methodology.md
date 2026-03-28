---
layout: default
title: "Methodology"
---
# Methodology

## eforge Multi-Agent Pipeline

eforge uses a multi-agent architecture to solve software engineering tasks:

1. **Planner** — Analyzes the issue (PRD) and creates a detailed implementation plan, breaking the work into discrete tasks with dependencies and verification criteria.
2. **Builder** — Executes each task in the plan, writing code changes according to the planner's specifications. Multiple builder agents can work in parallel on independent tasks.
3. **Reviewer** — Validates the implementation against the plan's acceptance criteria, running tests and checking for correctness.

This pipeline mirrors how experienced engineering teams operate: plan first, implement systematically, then verify.

## SWE-bench Lite

[SWE-bench](https://www.swebench.com/) is a benchmark for evaluating AI systems on real-world software engineering tasks. Each instance consists of a GitHub issue and a repository snapshot. The system must produce a patch (git diff) that resolves the issue.

**SWE-bench Lite** is a curated subset of 300 instances from the full SWE-bench dataset, selected to be more tractable while still representative. Instances span popular Python repositories including Django, scikit-learn, pytest, sphinx, and others.

An instance is considered **resolved** if:
- The generated patch applies cleanly to the repository
- All previously-failing tests now pass
- All previously-passing tests continue to pass

## Docker Harness

Each benchmark instance runs inside an isolated Docker container:

1. **Base images** — SWE-bench provides pre-built Docker images (`swebench/sweb.eval.x86_64.<id>:latest`) with the correct repository state and Python environment for each instance.
2. **eforge layer** — We build a layer on top (`eforge-bench/<instance_id>:latest`) that adds Node.js 24.x and the Claude Code CLI with eforge installed.
3. **Non-root execution** — Containers run as a non-root `eforge` user because Claude Code refuses `bypassPermissions` mode as root.
4. **PRD generation** — The harness generates an `issue.md` file from the GitHub issue text and an `eforge.yaml` configuration, mounted into the container at `/input`.
5. **Patch extraction** — After eforge completes, the harness extracts a git diff against the base commit.
6. **Artifact filtering** — Diffs for benchmark-specific files (`eforge.yaml`, `docs/swe-bench-issue.md`, `.eforge/`) are stripped from the final patch to avoid contaminating results.

## Instance Subset Rationale

Different benchmark runs may use different subsets of SWE-bench Lite instances. This happens for several reasons:

- **Cost management** — Each instance costs approximately $10–30 for eforge (multi-agent pipeline) or $2–5 for a vanilla Claude baseline. Running all 300 instances would cost thousands of dollars.
- **Iterative development** — During development, we run small "starter" subsets (typically 5 instances) to validate changes quickly before scaling up.
- **Targeted testing** — Some runs focus on specific repositories or difficulty levels to understand performance characteristics.
- **Timeout constraints** — Complex instances may require longer timeouts, affecting which instances are practical to include.

Results should be compared only across runs that use the same instance set.

## Known Limitations

- **Cost per instance** — The multi-agent pipeline is significantly more expensive than single-agent approaches. This limits the frequency and scale of benchmark runs.
- **Timeout constraints** — Some complex instances (e.g., `pytest-dev__pytest-5103`, which requires AST rewriting) consistently exceed timeout limits regardless of the allowed duration.
- **Dataset contamination** — SWE-bench Verified should be avoided as of February 2026 due to contamination concerns. We use SWE-bench Lite exclusively.
- **Non-determinism** — LLM-based agents produce different results across runs. A single run is not sufficient to establish reliable performance metrics.
- **Limited baseline comparison** — Currently only vanilla Claude (single-agent) baselines are supported. Comparison with other multi-agent systems requires separate tooling.
