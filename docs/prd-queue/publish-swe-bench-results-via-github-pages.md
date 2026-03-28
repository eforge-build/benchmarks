---
title: Publish SWE-bench Results via GitHub Pages
created: 2026-03-28
status: failed
---

# Publish SWE-bench Results via GitHub Pages

## Problem / Motivation

eforge benchmarks now produce real results (2/5 resolved on the latest run), but there is no way to publish or track them over time. There is no public-facing site showing methodology, latest results, or historical runs. Without a publishing mechanism, benchmark progress is invisible and untrackable.

## Goal

Ship a simple GitHub Pages site that displays methodology, latest SWE-bench results, and historical runs — updated via a manual publish script after each benchmark run.

## Approach

### Jekyll site in `docs/` on `main` branch

GitHub Pages serves directly from `docs/` — no build step, no separate branch required.

```
docs/
  _config.yml                    # Jekyll config (theme: minima)
  _data/
    runs.json                    # Append-only historical run data
  index.md                       # Homepage: latest results + history table
  methodology.md                 # Static: how eforge works, benchmark approach
  results/
    index.md                     # All runs table (regenerated)
    <timestamp>.md               # Per-run detail page (generated)
```

### `publish.py` — manual publish script (~200 lines, stdlib only)

**Usage:** `python publish.py results/2026-03-28T03-05-38/ [--notes "description"]`

**Steps:**

1. Load data from 3 sources:
   - `results/<timestamp>/config.json` — run config (instances, timeout, dataset)
   - `results/<timestamp>/eforge_metadata.jsonl` — per-instance timing, exit codes, failure reasons
   - `eforge.eforge_predictions.json` (repo root) — SWE-bench eval report (resolved/unresolved IDs)
2. Detect eforge version via `npm list -g eforge --json`
3. Build run summary and append to `docs/_data/runs.json` (duplicate check by timestamp)
4. Generate `docs/results/<timestamp>.md` — per-run detail page
5. Regenerate `docs/results/index.md` — all runs table
6. Regenerate `docs/index.md` — homepage with latest results
7. Print summary, remind user to commit + push (no auto-commit)

**Data per run in `runs.json`:**

- `timestamp`, `date`, `dataset`, `eforge_version`
- `num_instances`, `num_resolved`, `resolution_rate`
- `resolved_ids`, `unresolved_ids`, `empty_patch_ids`
- `per_instance`: `[{instance_id, status, failure_reason, duration_seconds, patch_lines}]`
- `notes` (optional)

### `docs/methodology.md` — static page

Written once, maintained by hand. Covers:

- What eforge is (multi-agent pipeline: planner, builder, reviewer)
- SWE-bench Lite and what "resolved" means
- Docker harness: how instances are run, PRD generation, patch extraction
- Why runs use different instance subsets
- Known limitations (cost, timeout, contamination)

### Files to create

| File | Type | Description |
|------|------|-------------|
| `docs/_config.yml` | Create | Jekyll config (minima theme, baseurl: `/benchmarks`) |
| `docs/index.md` | Generate | Homepage with latest results + history |
| `docs/methodology.md` | Create | Static methodology explanation |
| `docs/results/index.md` | Generate | All runs table |
| `docs/_data/runs.json` | Create | Empty `[]`, appended by `publish.py` |
| `publish.py` | Create | ~200 lines, stdlib only |

### Post-implementation steps

1. Run `python publish.py results/2026-03-28T03-05-38/ --notes "First published run"`
2. Review generated docs, commit + push
3. Enable GitHub Pages in repo settings: Source → main branch → `/docs` folder

## Scope

**In scope:**

- Jekyll site structure in `docs/` served via GitHub Pages from `main` branch
- `publish.py` script that reads benchmark output, generates/updates all site pages, and appends to `runs.json`
- Static `methodology.md` page covering eforge architecture, SWE-bench Lite, Docker harness, subset rationale, and known limitations
- Homepage (`index.md`) showing latest results and history table
- Per-run detail pages (`results/<timestamp>.md`) with per-instance tables
- All-runs index page (`results/index.md`)
- Append-only `runs.json` with duplicate-check by timestamp
- eforge version detection via `npm list -g eforge --json`

**Out of scope:**

- Automatic commits or pushes (script prints a reminder only)
- CI/CD or automated publishing pipeline
- Separate branch or external build step for GitHub Pages
- Any dependencies beyond Python stdlib for `publish.py`

## Acceptance Criteria

1. Running `python publish.py results/2026-03-28T03-05-38/` produces:
   - `docs/_data/runs.json` containing exactly 1 entry with correct data (timestamp, resolved/unresolved IDs, resolution rate, per-instance details)
   - `docs/results/2026-03-28T03-05-38.md` exists and contains a per-instance table
   - `docs/index.md` displays the latest results and a history table
   - `docs/results/index.md` displays an all-runs table
2. Running `publish.py` a second time on the same timestamp is rejected (duplicate check).
3. The generated markdown pages render correctly when served by Jekyll (verified via `bundle exec jekyll serve` or manual review).
4. `docs/methodology.md` exists as a static page covering: eforge multi-agent pipeline, SWE-bench Lite definition of "resolved," Docker harness details, subset rationale, and known limitations.
5. `docs/_config.yml` is configured with theme `minima` and baseurl `/benchmarks`.
6. `publish.py` uses only Python stdlib (no external dependencies) and is approximately 200 lines.
7. `publish.py` prints a summary after execution and reminds the user to commit and push.
