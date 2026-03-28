#!/usr/bin/env python3
"""
SWE-bench benchmark harness for eforge.

Runs eforge against SWE-bench instances inside Docker containers with the
correct Python environment, captures patches, and evaluates them.

Usage:
    python harness/run_benchmark.py --starter                # Curated starter set (Docker)
    python harness/run_benchmark.py --starter --baseline      # + vanilla Claude comparison
    python harness/run_benchmark.py --starter --eval          # + SWE-bench evaluation
    python harness/run_benchmark.py --starter --no-docker     # Run on host (no Docker)
    python harness/run_benchmark.py --instance-ids "pytest-dev__pytest-5227"
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from datasets import load_dataset


SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
REPOS_DIR = REPO_ROOT / "repos"
RESULTS_DIR = REPO_ROOT / "results"

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"

# Curated starter instances: medium difficulty, clear problem statements,
# manageable repo sizes, 40-70% solve rate across top agents.
STARTER_INSTANCES = [
    "scikit-learn__scikit-learn-10949",
    "scikit-learn__scikit-learn-13241",
    "pytest-dev__pytest-5103",
    "pytest-dev__pytest-5227",
    "sphinx-doc__sphinx-8273",
]


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_instances(
    num_instances: Optional[int] = None,
    instance_ids: Optional[List[str]] = None,
    starter: bool = False,
) -> List[dict]:
    """Load SWE-bench instances from the dataset."""
    print(f"Loading dataset: {DATASET_NAME}")
    ds = load_dataset(DATASET_NAME, split="test")

    if starter:
        instance_ids = STARTER_INSTANCES
        print(f"Using curated starter set: {len(instance_ids)} instances")

    if instance_ids:
        id_set = set(instance_ids)
        instances = [row for row in ds if row["instance_id"] in id_set]
        missing = id_set - {i["instance_id"] for i in instances}
        if missing:
            print(f"Warning: instances not found in dataset: {missing}")
    elif num_instances:
        instances = list(ds.select(range(min(num_instances, len(ds)))))
    else:
        instances = list(ds)

    print(f"Loaded {len(instances)} instances")
    for inst in instances:
        print(f"  - {inst['instance_id']} ({inst['repo']})")
    print()
    return instances


# ---------------------------------------------------------------------------
# PRD / config generation
# ---------------------------------------------------------------------------

def make_prd_content(instance: dict) -> str:
    """Generate PRD content from a SWE-bench instance."""
    problem = instance["problem_statement"]
    hints = instance.get("hints_text", "")
    repo = instance["repo"]

    content = f"# Bug Fix: {instance['instance_id']}\n\n"
    content += f"## Repository\n\n`{repo}`\n\n"
    content += f"## Problem Description\n\n{problem}\n"
    if hints:
        content += f"\n## Additional Context from Issue Discussion\n\n{hints}\n"
    content += "\n## Requirements\n\n"
    content += "1. Fix the bug described above with minimal changes\n"
    content += "2. Do not modify test files\n"
    content += "3. Ensure existing tests continue to pass\n"
    content += "4. Prefer the simplest correct fix over refactoring\n"
    return content


EFORGE_YAML = """\
# Minimal config for SWE-bench benchmarking
# Validation is discovered automatically by eforge from the project
validate: []
"""


# ---------------------------------------------------------------------------
# Docker mode
# ---------------------------------------------------------------------------

def get_swebench_image_name(instance: dict) -> str:
    """Get the SWE-bench Docker image name for an instance.

    SWE-bench evaluation images follow the naming convention:
        swebench/sweb.eval.x86_64.<modified_id>:latest
    where __ in instance_id becomes _1776_ in the image name.
    """
    instance_id = instance["instance_id"]
    modified_id = instance_id.replace("__", "_1776_")
    return f"swebench/sweb.eval.x86_64.{modified_id}:latest"


def prepare_docker_images(instances: list[dict]):
    """Build SWE-bench Docker images for the given instances."""
    instance_ids = [i["instance_id"] for i in instances]
    print("Preparing SWE-bench Docker images...")
    print("  (This may take a while on first run — building Python environments)")

    subprocess.run(
        [
            sys.executable, "-m", "swebench.harness.prepare_images",
            "--dataset_name", DATASET_NAME,
            "--instance_ids", *instance_ids,
            "--namespace", "swebench",
            "--tag", "latest",
            "--env_image_tag", "latest",
        ],
        check=True,
    )

    print("  SWE-bench images ready.\n")


def build_eforge_image(base_image: str, instance_id: str) -> str:
    """Build an eforge-enabled Docker image on top of a SWE-bench base."""
    tag = f"eforge-bench/{instance_id}:latest"

    rebuild = os.environ.get("EFORGE_BENCH_REBUILD")
    if not rebuild:
        result = subprocess.run(
            ["docker", "images", "-q", tag],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            return tag

    print(f"  Building eforge layer on {base_image}...")
    cache_args = ["--no-cache"] if rebuild else []
    result = subprocess.run(
        [
            "docker", "build",
            "--platform", "linux/amd64",
            *cache_args,
            "--build-arg", f"BASE_IMAGE={base_image}",
            "-t", tag,
            "-f", str(REPO_ROOT / "Dockerfile.eforge"),
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Docker build failed:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"Failed to build eforge image for {instance_id}")
    return tag


def run_eforge_docker(instance: dict, timeout: int = 900) -> dict:
    """Run eforge inside a SWE-bench Docker container."""
    instance_id = instance["instance_id"]
    base_commit = instance["base_commit"]
    start_time = time.time()

    # Get/build Docker images
    swebench_image = get_swebench_image_name(instance)
    eforge_image = build_eforge_image(swebench_image, instance_id)

    # Create temp directories for input/output
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # Write PRD and config
        (input_dir / "issue.md").write_text(make_prd_content(instance))
        (input_dir / "eforge.yaml").write_text(EFORGE_YAML)

        # Auth: pass API key to container
        auth_args = []
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            auth_args.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
        else:
            print("  Warning: ANTHROPIC_API_KEY not set, eforge will fail to authenticate")


        # Run eforge in container
        # Expose monitor port (4567) so builds can be watched from host
        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-v", f"{input_dir}:/input:ro",
                    "-v", f"{output_dir}:/output",
                    *auth_args,
                    "-p", "4566:4567",
                    "-e", f"BASE_COMMIT={base_commit}",
                    "-e", f"TIMEOUT={timeout}",
                    eforge_image,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 60,  # Extra buffer for container overhead
            )
            container_exit = result.returncode
        except subprocess.TimeoutExpired:
            container_exit = -1

        duration = time.time() - start_time

        # Read results from output directory
        exit_code_file = output_dir / "exit_code"
        patch_file = output_dir / "raw_patch.diff"
        stdout_file = output_dir / "stdout.log"
        stderr_file = output_dir / "stderr.log"

        exit_code = int(exit_code_file.read_text().strip()) if exit_code_file.exists() else container_exit
        patch = patch_file.read_text() if patch_file.exists() else ""
        stdout = stdout_file.read_text() if stdout_file.exists() else ""
        stderr = stderr_file.read_text() if stderr_file.exists() else ""

        # Filter benchmark artifacts from patch
        patch = filter_benchmark_artifacts(patch)

        return {
            "instance_id": instance_id,
            "model_name_or_path": "eforge",
            "model_patch": patch,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 1),
            "stdout_tail": stdout[-5000:] if stdout else "",
            "stderr_tail": stderr[-2000:] if stderr else "",
            "failure_reason": classify_failure(exit_code, stdout, stderr),
            "mode": "docker",
        }


# ---------------------------------------------------------------------------
# Host mode (no Docker)
# ---------------------------------------------------------------------------

def setup_repo(instance: dict) -> Path:
    """Clone the repo and checkout the base commit."""
    repo = instance["repo"]
    base_commit = instance["base_commit"]
    repo_dir = REPOS_DIR / repo.replace("/", "__")

    if repo_dir.exists():
        print(f"  Resetting to {base_commit[:8]}")
        subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "checkout", "-f", base_commit], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, capture_output=True, check=True)
        return repo_dir

    clone_url = f"https://github.com/{repo}.git"
    print(f"  Cloning {repo}...")
    subprocess.run(["git", "clone", "--quiet", clone_url, str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-f", base_commit], cwd=repo_dir, capture_output=True, check=True)
    return repo_dir


def run_eforge_host(instance: dict, repo_dir: Path, timeout: int = 900) -> dict:
    """Run eforge directly on the host (no Docker)."""
    instance_id = instance["instance_id"]
    start_time = time.time()

    # Write config and PRD
    (repo_dir / "eforge.yaml").write_text(EFORGE_YAML)
    prd_dir = repo_dir / "docs"
    prd_dir.mkdir(exist_ok=True)
    prd_path = prd_dir / "swe-bench-issue.md"
    prd_path.write_text(make_prd_content(instance))

    # Commit baseline
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "benchmark baseline", "--allow-empty"], cwd=repo_dir, capture_output=True)
    baseline_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True,
    ).stdout.strip()

    try:
        result = subprocess.run(
            ["eforge", "build", str(prd_path), "--foreground", "--auto", "--no-plugins"],
            cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = f"Timeout after {timeout}s"

    duration = time.time() - start_time

    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    diff_result = subprocess.run(
        ["git", "diff", "--cached", baseline_sha], cwd=repo_dir, capture_output=True, text=True,
    )
    patch = filter_benchmark_artifacts(diff_result.stdout)

    return {
        "instance_id": instance_id,
        "model_name_or_path": "eforge",
        "model_patch": patch,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 1),
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-2000:] if stderr else "",
        "mode": "host",
    }


def run_baseline(instance: dict, repo_dir: Path, timeout: int = 300) -> dict:
    """Run vanilla Claude (no eforge) against the same instance."""
    instance_id = instance["instance_id"]
    base_commit = instance["base_commit"]
    start_time = time.time()

    subprocess.run(["git", "checkout", "-f", base_commit], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline", "--allow-empty"], cwd=repo_dir, capture_output=True)

    problem = instance["problem_statement"]
    hints = instance.get("hints_text", "")
    prompt = f"Fix this bug in the repository:\n\n{problem}"
    if hints:
        prompt += f"\n\nAdditional context:\n{hints}"
    prompt += "\n\nMake the minimal changes necessary. Do not modify test files."

    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", prompt],
            cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
        )
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
    except FileNotFoundError:
        print("  Warning: 'claude' CLI not found, skipping baseline")
        return None

    duration = time.time() - start_time
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "HEAD~1"], cwd=repo_dir, capture_output=True, text=True,
    )

    return {
        "instance_id": instance_id,
        "model_name_or_path": "claude-baseline",
        "model_patch": diff_result.stdout,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 1),
    }


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def classify_failure(exit_code: int, stdout: str, stderr: str) -> str:
    """Classify the eforge failure reason from its output."""
    if exit_code == 0:
        return "success"
    if exit_code == 124 or exit_code == -1:
        return "timeout"

    # Check stdout for eforge pipeline status markers
    if "error_max_turns" in stdout:
        return "planner_max_turns"
    if "Merge failed" in stdout:
        # Extract review info if available
        if "critical" in stdout:
            return "merge_failed_after_review"
        return "merge_failed"
    if "Validation failed" in stdout and "Build complete" not in stdout:
        return "validation_failed"
    if "Validation failed" in stdout and "Build complete" in stdout:
        return "validation_failed_but_completed"
    if "Compile complete" in stdout and "Scheduling" in stdout and "Build complete" not in stdout:
        return "builder_failed"
    if "Compile complete" not in stdout:
        return "compile_failed"

    return f"unknown_exit_{exit_code}"


def filter_benchmark_artifacts(patch: str) -> str:
    """Remove diffs for files we added (PRD, eforge.yaml) from the patch."""
    if not patch:
        return patch

    filtered_hunks = []
    current_hunk = []
    skip = False

    for line in patch.split("\n"):
        if line.startswith("diff --git"):
            if current_hunk and not skip:
                filtered_hunks.append("\n".join(current_hunk))
            current_hunk = [line]
            skip = any(
                artifact in line
                for artifact in [
                    "docs/swe-bench-issue.md",
                    "docs/prd-queue/",
                    "eforge.yaml",
                    ".eforge/",
                    "plans/",
                    ".md.lock",
                ]
            )
        else:
            current_hunk.append(line)

    if current_hunk and not skip:
        filtered_hunks.append("\n".join(current_hunk))

    return "\n".join(filtered_hunks)


def save_predictions(predictions: list[dict], run_dir: Path, name: str) -> Path:
    pred_path = run_dir / f"{name}_predictions.jsonl"
    with open(pred_path, "w") as f:
        for pred in predictions:
            entry = {
                "instance_id": pred["instance_id"],
                "model_name_or_path": pred["model_name_or_path"],
                "model_patch": pred["model_patch"],
            }
            f.write(json.dumps(entry) + "\n")
    return pred_path


def save_run_metadata(predictions: list[dict], run_dir: Path, name: str):
    meta_path = run_dir / f"{name}_metadata.jsonl"
    with open(meta_path, "w") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")


def run_evaluation(predictions_path: Path, run_dir: Path, dataset_name: str):
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
            capture_output=True, text=True, timeout=3600,
        )
        print(result.stdout[-3000:] if result.stdout else "")
        if result.stderr:
            print(result.stderr[-1000:])
    except subprocess.TimeoutExpired:
        print("  Evaluation timed out after 1 hour")


def print_summary(predictions: list[dict], name: str):
    total = len(predictions)
    has_patch = sum(1 for p in predictions if p["model_patch"].strip())
    succeeded = sum(1 for p in predictions if p.get("exit_code") == 0)
    total_time = sum(p.get("duration_seconds", 0) for p in predictions)

    # Group by failure reason
    from collections import Counter
    reasons = Counter(p.get("failure_reason", "unknown") for p in predictions)

    print(f"\n{'='*60}")
    print(f"  {name} Run Summary")
    print(f"{'='*60}")
    print(f"  Instances:      {total}")
    print(f"  Succeeded:      {succeeded}/{total}")
    print(f"  Produced patch: {has_patch}/{total}")
    print(f"  Total time:     {total_time:.0f}s ({total_time/60:.1f}m)")
    if total > 0:
        print(f"  Avg time:       {total_time/total:.0f}s per instance")

    if len(reasons) > 1 or "success" not in reasons:
        print(f"\n  Failure breakdown:")
        for reason, count in reasons.most_common():
            if reason == "success":
                continue
            print(f"    {reason}: {count}")

    # Per-instance details
    print(f"\n  {'Instance':<45} {'Status':<12} {'Patch':>6} {'Time':>8}")
    print(f"  {'-'*75}")
    for p in predictions:
        iid = p["instance_id"]
        reason = p.get("failure_reason", "unknown")
        patch_lines = len(p["model_patch"].strip().split("\n")) if p["model_patch"].strip() else 0
        dur = p.get("duration_seconds", 0)
        print(f"  {iid:<45} {reason:<12} {patch_lines:>4}L  {dur:>6.0f}s")

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run eforge against SWE-bench instances")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--starter", action="store_true", help="Use curated 5-instance starter set")
    group.add_argument("--instances", type=int, help="Number of instances (from start of dataset)")
    group.add_argument("--instance-ids", type=str, help="Comma-separated instance IDs")

    parser.add_argument("--no-docker", action="store_true", help="Run on host instead of Docker (not recommended)")
    parser.add_argument("--baseline", action="store_true", help="Also run vanilla Claude baseline")
    parser.add_argument("--timeout", type=int, default=900, help="Per-instance timeout in seconds (default: 900)")
    parser.add_argument("--eval", action="store_true", help="Run SWE-bench evaluation after generating patches")
    parser.add_argument("--dataset", type=str, default=DATASET_NAME, help=f"Dataset name (default: {DATASET_NAME})")
    parser.add_argument("--skip-eforge", action="store_true", help="Skip eforge run (e.g., only run baseline)")
    args = parser.parse_args()

    use_docker = not args.no_docker

    instance_ids = args.instance_ids.split(",") if args.instance_ids else None
    instances = load_instances(args.instances, instance_ids, starter=args.starter)

    if not instances:
        print("No instances to process")
        return

    # Create timestamped results directory
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = RESULTS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Results directory: {run_dir}")
    print(f"Mode: {'Docker' if use_docker else 'host'}\n")

    # Prepare Docker images if needed
    if use_docker and not args.skip_eforge:
        prepare_docker_images(instances)

    # Run eforge
    if not args.skip_eforge:
        eforge_predictions = []
        for i, instance in enumerate(instances):
            instance_id = instance["instance_id"]
            print(f"[{i+1}/{len(instances)}] {instance_id}")

            if use_docker:
                print(f"  Building eforge Docker layer...")
                print(f"  Running eforge in Docker (timeout: {args.timeout}s)...")
                pred = run_eforge_docker(instance, timeout=args.timeout)
            else:
                print("  Setting up repo...")
                repo_dir = setup_repo(instance)
                print("  Writing eforge config + PRD...")
                print(f"  Running eforge on host (timeout: {args.timeout}s)...")
                pred = run_eforge_host(instance, repo_dir, timeout=args.timeout)

            eforge_predictions.append(pred)

            patch_lines = len(pred["model_patch"].strip().split("\n")) if pred["model_patch"].strip() else 0
            reason = pred.get("failure_reason", "")
            status = "timeout" if pred["exit_code"] == -1 else ("ok" if pred["exit_code"] == 0 else f"FAILED")
            reason_str = f" ({reason})" if reason and reason != "success" else ""
            print(f"  Done: {status}{reason_str}, {patch_lines} lines of patch, {pred['duration_seconds']}s")
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

            repo_dir = REPOS_DIR / instance["repo"].replace("/", "__")
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
        "mode": "docker" if use_docker else "host",
        "ran_eforge": not args.skip_eforge,
        "ran_baseline": args.baseline,
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2))

    print(f"Results saved to: {run_dir}")


if __name__ == "__main__":
    main()
