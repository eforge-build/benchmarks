#!/usr/bin/env python3
"""
SWE-bench benchmark harness for eforge.

Runs eforge (and optionally a vanilla Claude baseline) against SWE-bench
instances, captures patches, and evaluates them using the SWE-bench harness.

Usage:
    python harness/run_benchmark.py --instances 5          # Quick smoke test
    python harness/run_benchmark.py --instances 20         # Phase 1
    python harness/run_benchmark.py --instance-ids "astropy__astropy-12907,django__django-11179"
    python harness/run_benchmark.py --instances 5 --baseline  # Also run vanilla Claude
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from datasets import load_dataset


SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
REPOS_DIR = REPO_ROOT / "repos"
RESULTS_DIR = REPO_ROOT / "results"

# SWE-bench dataset to use (Lite is small and practical for initial testing)
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"


def load_instances(num_instances: int | None = None, instance_ids: list[str] | None = None) -> list[dict]:
    """Load SWE-bench instances from the dataset."""
    print(f"Loading dataset: {DATASET_NAME}")
    ds = load_dataset(DATASET_NAME, split="test")

    if instance_ids:
        instances = [row for row in ds if row["instance_id"] in instance_ids]
        missing = set(instance_ids) - {i["instance_id"] for i in instances}
        if missing:
            print(f"Warning: instances not found: {missing}")
    elif num_instances:
        instances = list(ds.select(range(min(num_instances, len(ds)))))
    else:
        instances = list(ds)

    print(f"Loaded {len(instances)} instances")
    return instances


def setup_repo(instance: dict) -> Path:
    """Clone the repo and checkout the base commit for a SWE-bench instance."""
    instance_id = instance["instance_id"]
    repo = instance["repo"]
    base_commit = instance["base_commit"]

    repo_dir = REPOS_DIR / instance_id.replace("/", "__")

    if repo_dir.exists():
        # Reset to the correct commit if repo already cloned
        print(f"  Resetting existing repo to {base_commit[:8]}")
        subprocess.run(
            ["git", "checkout", "-f", base_commit],
            cwd=repo_dir, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "clean", "-fdx"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        return repo_dir

    # Clone fresh
    clone_url = f"https://github.com/{repo}.git"
    print(f"  Cloning {repo}...")
    subprocess.run(
        ["git", "clone", "--quiet", clone_url, str(repo_dir)],
        check=True, capture_output=True,
    )

    print(f"  Checking out {base_commit[:8]}")
    subprocess.run(
        ["git", "checkout", "-f", base_commit],
        cwd=repo_dir, capture_output=True, check=True,
    )

    return repo_dir


def write_prd(instance: dict, repo_dir: Path) -> Path:
    """Write the SWE-bench problem statement as a PRD file for eforge."""
    prd_dir = repo_dir / "docs"
    prd_dir.mkdir(exist_ok=True)
    prd_path = prd_dir / "swe-bench-issue.md"

    problem = instance["problem_statement"]
    hints = instance.get("hints_text", "")

    content = f"# Issue: {instance['instance_id']}\n\n"
    content += f"## Problem\n\n{problem}\n"
    if hints:
        content += f"\n## Additional Context\n\n{hints}\n"
    content += "\n## Instructions\n\n"
    content += "Fix the issue described above. Make the minimal changes necessary "
    content += "to resolve the problem while ensuring existing tests continue to pass.\n"

    prd_path.write_text(content)
    return prd_path


def run_eforge(instance: dict, repo_dir: Path, prd_path: Path, timeout: int = 600) -> dict:
    """Run eforge against a SWE-bench instance and capture the patch."""
    instance_id = instance["instance_id"]
    start_time = time.time()

    # Record the starting state so we can capture the diff
    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "stash"],
        cwd=repo_dir, capture_output=True,
    )

    try:
        result = subprocess.run(
            [
                "eforge", "build", str(prd_path),
                "--foreground",
                "--auto",
                "--no-monitor",
                "--no-plugins",
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = f"Timeout after {timeout}s"

    duration = time.time() - start_time

    # Capture the diff (everything eforge changed)
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    patch = diff_result.stdout

    # Also capture any new untracked files
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if untracked.stdout.strip():
        # Add untracked files to get their content in the diff
        subprocess.run(
            ["git", "add", "-N"] + untracked.stdout.strip().split("\n"),
            cwd=repo_dir, capture_output=True,
        )
        untracked_diff = subprocess.run(
            ["git", "diff"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        patch += untracked_diff.stdout

    return {
        "instance_id": instance_id,
        "model_name_or_path": "eforge",
        "model_patch": patch,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 1),
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-2000:] if stderr else "",
    }


def run_baseline(instance: dict, repo_dir: Path, timeout: int = 300) -> dict:
    """Run vanilla Claude (no eforge) against the same instance for comparison."""
    instance_id = instance["instance_id"]
    start_time = time.time()

    # Reset repo to clean state
    subprocess.run(["git", "checkout", "-f", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, capture_output=True)

    problem = instance["problem_statement"]
    hints = instance.get("hints_text", "")
    prompt = f"Fix this issue in the repository:\n\n{problem}"
    if hints:
        prompt += f"\n\nAdditional context:\n{hints}"
    prompt += "\n\nMake the minimal changes necessary to fix the issue."

    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", prompt],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
    except FileNotFoundError:
        print("  Warning: 'claude' CLI not found, skipping baseline")
        return None

    duration = time.time() - start_time

    # Capture diff
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    patch = diff_result.stdout

    return {
        "instance_id": instance_id,
        "model_name_or_path": "claude-baseline",
        "model_patch": patch,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 1),
    }


def save_predictions(predictions: list[dict], run_dir: Path, name: str) -> Path:
    """Save predictions in SWE-bench JSONL format."""
    pred_path = run_dir / f"{name}_predictions.jsonl"
    with open(pred_path, "w") as f:
        for pred in predictions:
            # SWE-bench evaluation only needs these three fields
            entry = {
                "instance_id": pred["instance_id"],
                "model_name_or_path": pred["model_name_or_path"],
                "model_patch": pred["model_patch"],
            }
            f.write(json.dumps(entry) + "\n")
    return pred_path


def save_run_metadata(predictions: list[dict], run_dir: Path, name: str):
    """Save full run metadata including timing and logs."""
    meta_path = run_dir / f"{name}_metadata.jsonl"
    with open(meta_path, "w") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")


def run_evaluation(predictions_path: Path, run_dir: Path, dataset_name: str):
    """Run the SWE-bench evaluation harness."""
    print(f"\nRunning SWE-bench evaluation on {predictions_path.name}...")
    run_id = predictions_path.stem

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "swebench.harness.run_evaluation",
                "--dataset_name", dataset_name,
                "--predictions_path", str(predictions_path),
                "--max_workers", str(min(os.cpu_count() or 4, 8)),
                "--run_id", run_id,
            ],
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max for evaluation
        )
        print(result.stdout[-3000:] if result.stdout else "")
        if result.stderr:
            print(result.stderr[-1000:])
    except subprocess.TimeoutExpired:
        print("  Evaluation timed out after 1 hour")


def print_summary(predictions: list[dict], name: str):
    """Print a quick summary of the run."""
    total = len(predictions)
    has_patch = sum(1 for p in predictions if p["model_patch"].strip())
    timed_out = sum(1 for p in predictions if p.get("exit_code") == -1)
    failed = sum(1 for p in predictions if p.get("exit_code", 0) not in (0, -1))
    total_time = sum(p.get("duration_seconds", 0) for p in predictions)

    print(f"\n{'='*60}")
    print(f"  {name} Run Summary")
    print(f"{'='*60}")
    print(f"  Instances:     {total}")
    print(f"  Produced patch: {has_patch}/{total}")
    print(f"  Timed out:     {timed_out}")
    print(f"  Failed:        {failed}")
    print(f"  Total time:    {total_time:.0f}s ({total_time/60:.1f}m)")
    if total > 0:
        print(f"  Avg time:      {total_time/total:.0f}s per instance")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Run eforge against SWE-bench instances")
    parser.add_argument("--instances", type=int, help="Number of instances to run")
    parser.add_argument("--instance-ids", type=str, help="Comma-separated instance IDs")
    parser.add_argument("--baseline", action="store_true", help="Also run vanilla Claude baseline")
    parser.add_argument("--timeout", type=int, default=600, help="Per-instance timeout in seconds (default: 600)")
    parser.add_argument("--eval", action="store_true", help="Run SWE-bench evaluation after generating patches")
    parser.add_argument("--dataset", type=str, default=DATASET_NAME, help=f"Dataset name (default: {DATASET_NAME})")
    parser.add_argument("--skip-eforge", action="store_true", help="Skip eforge run (e.g., only run baseline)")
    args = parser.parse_args()

    if not args.instances and not args.instance_ids:
        parser.error("Specify --instances N or --instance-ids 'id1,id2,...'")

    instance_ids = args.instance_ids.split(",") if args.instance_ids else None
    instances = load_instances(args.instances, instance_ids)

    if not instances:
        print("No instances to process")
        return

    # Create timestamped results directory
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = RESULTS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Results directory: {run_dir}\n")

    # Run eforge
    if not args.skip_eforge:
        eforge_predictions = []
        for i, instance in enumerate(instances):
            instance_id = instance["instance_id"]
            print(f"[{i+1}/{len(instances)}] {instance_id}")

            print("  Setting up repo...")
            repo_dir = setup_repo(instance)

            print("  Writing PRD...")
            prd_path = write_prd(instance, repo_dir)

            print(f"  Running eforge (timeout: {args.timeout}s)...")
            pred = run_eforge(instance, repo_dir, prd_path, timeout=args.timeout)
            eforge_predictions.append(pred)

            patch_lines = len(pred["model_patch"].strip().split("\n")) if pred["model_patch"].strip() else 0
            status = "timeout" if pred["exit_code"] == -1 else ("ok" if pred["exit_code"] == 0 else f"exit {pred['exit_code']}")
            print(f"  Done: {status}, {patch_lines} lines of patch, {pred['duration_seconds']}s")
            print()

        pred_path = save_predictions(eforge_predictions, run_dir, "eforge")
        save_run_metadata(eforge_predictions, run_dir, "eforge")
        print_summary(eforge_predictions, "eforge")

        if args.eval:
            run_evaluation(pred_path, run_dir, args.dataset)

    # Run baseline
    if args.baseline:
        baseline_predictions = []
        for i, instance in enumerate(instances):
            instance_id = instance["instance_id"]
            print(f"[baseline {i+1}/{len(instances)}] {instance_id}")

            repo_dir = REPOS_DIR / instance_id.replace("/", "__")
            if not repo_dir.exists():
                print("  Setting up repo...")
                repo_dir = setup_repo(instance)

            print(f"  Running vanilla Claude (timeout: {args.timeout}s)...")
            pred = run_baseline(instance, repo_dir, timeout=args.timeout)
            if pred:
                baseline_predictions.append(pred)

            print()

        if baseline_predictions:
            pred_path = save_predictions(baseline_predictions, run_dir, "claude-baseline")
            save_run_metadata(baseline_predictions, run_dir, "claude-baseline")
            print_summary(baseline_predictions, "claude-baseline")

            if args.eval:
                run_evaluation(pred_path, run_dir, args.dataset)

    # Save run config
    config = {
        "timestamp": timestamp,
        "dataset": args.dataset,
        "num_instances": len(instances),
        "instance_ids": [i["instance_id"] for i in instances],
        "timeout": args.timeout,
        "ran_eforge": not args.skip_eforge,
        "ran_baseline": args.baseline,
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2))

    print(f"Results saved to: {run_dir}")


if __name__ == "__main__":
    main()
