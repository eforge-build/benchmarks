#!/usr/bin/env python3
"""Publish SWE-bench benchmark results to the Jekyll site in docs/."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_DIR = SCRIPT_DIR / "docs"
DATA_DIR = DOCS_DIR / "_data"
RUNS_JSON = DATA_DIR / "runs.json"
RESULTS_DIR = DOCS_DIR / "results"


def detect_eforge_version():
    """Detect globally installed eforge version via npm."""
    try:
        out = subprocess.run(
            ["npm", "list", "-g", "eforge", "--json"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        return json.loads(out).get("dependencies", {}).get("eforge", {}).get("version", "unknown")
    except Exception:
        return "unknown"


def count_patch_lines(patch_text):
    """Count +/- lines in a patch, excluding +++ and --- headers."""
    if not patch_text:
        return 0
    return sum(
        1 for line in patch_text.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++") and not line.startswith("---")
    )


def load_jsonl(path):
    """Load a JSONL file as a list of dicts."""
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_per_instance_data(instance_ids, metadata_by_id, eval_report):
    """Build per-instance result data from metadata and eval report."""
    resolved = set(eval_report.get("resolved_ids", []))
    empty = set(eval_report.get("empty_patch_ids", []))
    instances = []
    for iid in instance_ids:
        if iid in resolved:
            status, reason = "resolved", None
        elif iid in empty:
            status, reason = "empty_patch", "empty patch"
        else:
            status, reason = "unresolved", "tests failed"
        patch = metadata_by_id.get(iid, {}).get("model_patch", "")
        instances.append({"instance_id": iid, "status": status,
                          "failure_reason": reason, "duration_seconds": None,
                          "patch_lines": count_patch_lines(patch)})
    return instances


def generate_run_page(entry, path):
    """Generate per-run detail Markdown page."""
    ts, insts = entry["timestamp"], entry["instances"]
    unresolved_n = entry["num_instances"] - entry["num_resolved"] - entry["num_empty_patch"]
    lines = [
        "---", "layout: default", f'title: "Run {ts}"', "---", f"# Run {ts}", "",
        f"**Date**: {ts} | **Dataset**: {entry['dataset']} | **eforge version**: {entry['eforge_version']}",
        "", "## Summary", "", "| Metric | Value |", "|--------|-------|",
        f"| Instances | {entry['num_instances']} |",
        f"| Resolved | {entry['num_resolved']} ({entry['resolution_rate']}%) |",
        f"| Unresolved | {unresolved_n} |",
        f"| Empty Patch | {entry['num_empty_patch']} |",
        "", "## Per-Instance Results", "",
        "| Instance | Status | Patch Lines | Failure Reason |",
        "|----------|--------|-------------|----------------|",
    ]
    for i in insts:
        lines.append(f"| {i['instance_id']} | {i['status']} | {i['patch_lines']} | {i['failure_reason'] or ''} |")
    for label, pred in [("Resolved", lambda i: i["status"] == "resolved"),
                        ("Unresolved", lambda i: i["status"] != "resolved")]:
        lines += ["", f"## {label}", ""]
        matched = [i for i in insts if pred(i)]
        lines += [f"- {i['instance_id']}" for i in matched] if matched else ["_None_"]
    lines.append("")
    path.write_text("\n".join(lines))


def generate_all_runs_index(runs):
    """Generate the all-runs index page."""
    sorted_runs = sorted(runs, key=lambda r: r["timestamp"], reverse=True)
    lines = [
        "---", "layout: default", 'title: "All Runs"', "---", "# All Benchmark Runs", "",
        "| Date | eforge Version | Dataset | Instances | Resolved | Rate | Details |",
        "|------|---------------|---------|-----------|----------|------|---------|",
    ]
    for r in sorted_runs:
        t = r["timestamp"]
        lines.append(f"| {t} | {r['eforge_version']} | {r['dataset']} | {r['num_instances']} | {r['num_resolved']} | {r['resolution_rate']}% | [View]({t}.html) |")
    lines.append("")
    RESULTS_DIR.joinpath("index.md").write_text("\n".join(lines))


def generate_homepage(runs):
    """Generate the homepage with latest run summary and history."""
    sorted_runs = sorted(runs, key=lambda r: r["timestamp"], reverse=True)
    latest = sorted_runs[0] if sorted_runs else None
    lines = ["---", "layout: default", 'title: "eforge SWE-bench Results"', "---",
             "# eforge SWE-bench Results", ""]
    if latest:
        lines += [
            "## Latest Run", "",
            f"**{latest['timestamp']}** — {latest['num_resolved']}/{latest['num_instances']} resolved "
            f"({latest['resolution_rate']}%) on {latest['dataset']} with eforge {latest['eforge_version']}",
            "", f"[View details](results/{latest['timestamp']}.html)", "",
        ]
    lines += ["## History", "",
              "| Date | eforge Version | Instances | Resolved | Rate | Details |",
              "|------|---------------|-----------|----------|------|---------|"]
    for r in sorted_runs[:10]:
        t = r["timestamp"]
        lines.append(f"| {t} | {r['eforge_version']} | {r['num_instances']} | {r['num_resolved']} | {r['resolution_rate']}% | [View](results/{t}.html) |")
    lines.append("")
    DOCS_DIR.joinpath("index.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Publish SWE-bench results to Jekyll site.")
    parser.add_argument("results_dir", help="Path to results directory (e.g. results/2026-03-28T03-05-38/)")
    parser.add_argument("--notes", default=None, help="Optional notes for the run entry")
    args = parser.parse_args()

    results_path = Path(args.results_dir).resolve()
    if not results_path.is_dir():
        print(f"Error: results directory not found: {results_path}", file=sys.stderr)
        sys.exit(1)

    timestamp = results_path.name

    # Load inputs
    config_path = results_path / "config.json"
    if not config_path.exists():
        print(f"Error: config.json not found in {results_path}", file=sys.stderr)
        sys.exit(1)
    config = json.loads(config_path.read_text())

    metadata_by_id = {}
    metadata_path = results_path / "eforge_metadata.jsonl"
    if metadata_path.exists():
        metadata_by_id = {e["instance_id"]: e for e in load_jsonl(metadata_path)}

    eval_path = SCRIPT_DIR / "eforge.eforge_predictions.json"
    if not eval_path.exists():
        print(f"Error: eval report not found: {eval_path}", file=sys.stderr)
        sys.exit(1)
    eval_report = json.loads(eval_path.read_text())

    # Build run data
    instances = build_per_instance_data(config["instance_ids"], metadata_by_id, eval_report)
    num_resolved = sum(1 for i in instances if i["status"] == "resolved")
    num_empty = sum(1 for i in instances if i["status"] == "empty_patch")
    num_instances = len(instances)
    rate = round(num_resolved / num_instances * 100, 1) if num_instances else 0.0
    resolved_ids = [i["instance_id"] for i in instances if i["status"] == "resolved"]

    run_entry = {
        "timestamp": timestamp, "dataset": config["dataset"],
        "num_instances": num_instances, "num_resolved": num_resolved,
        "num_empty_patch": num_empty, "resolution_rate": rate,
        "eforge_version": detect_eforge_version(), "resolved_ids": resolved_ids,
        "notes": args.notes, "instances": instances,
    }

    # Duplicate check
    runs = json.loads(RUNS_JSON.read_text()) if RUNS_JSON.exists() else []
    if any(r["timestamp"] == timestamp for r in runs):
        print(f"Error: duplicate timestamp {timestamp} already exists in runs.json", file=sys.stderr)
        sys.exit(1)

    # Write data and generate pages
    runs.append(run_entry)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_JSON.write_text(json.dumps(runs, indent=2) + "\n")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    generate_run_page(run_entry, RESULTS_DIR / f"{timestamp}.md")
    generate_all_runs_index(runs)
    generate_homepage(runs)

    # Summary
    print(f"Published run {timestamp}: {num_resolved}/{num_instances} resolved ({rate}%)")
    print(f"  Resolved: {', '.join(resolved_ids) if resolved_ids else 'none'}")
    print("\nRemember to commit and push to publish to GitHub Pages:")
    print("  git add docs/ && git commit -m 'Publish benchmark results' && git push")


if __name__ == "__main__":
    main()
