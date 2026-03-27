#!/usr/bin/env python3
"""
Compare eforge vs baseline results from a benchmark run.

Usage:
    python analysis/compare.py results/2026-03-27T12-00-00/
"""

import json
import sys
from pathlib import Path


def load_metadata(run_dir: Path, name: str) -> dict[str, dict]:
    """Load run metadata keyed by instance_id."""
    meta_path = run_dir / f"{name}_metadata.jsonl"
    if not meta_path.exists():
        return {}
    entries = {}
    with open(meta_path) as f:
        for line in f:
            entry = json.loads(line)
            entries[entry["instance_id"]] = entry
    return entries


def main():
    if len(sys.argv) < 2:
        print("Usage: python analysis/compare.py <results-dir>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    eforge = load_metadata(run_dir, "eforge")
    baseline = load_metadata(run_dir, "claude-baseline")

    if not eforge:
        print("No eforge results found")
        sys.exit(1)

    print(f"{'Instance':<45} {'eforge':>10} {'baseline':>10} {'eforge patch':>12} {'baseline patch':>14}")
    print("-" * 95)

    for iid in sorted(eforge.keys()):
        e = eforge[iid]
        b = baseline.get(iid)

        e_status = "timeout" if e["exit_code"] == -1 else ("ok" if e["exit_code"] == 0 else "fail")
        e_patch = len(e["model_patch"].strip().split("\n")) if e["model_patch"].strip() else 0

        if b:
            b_status = "timeout" if b["exit_code"] == -1 else ("ok" if b["exit_code"] == 0 else "fail")
            b_patch = len(b["model_patch"].strip().split("\n")) if b["model_patch"].strip() else 0
        else:
            b_status = "-"
            b_patch = "-"

        print(f"{iid:<45} {e_status:>10} {b_status:>10} {e_patch:>12} {b_patch:>14}")

    # Summary
    e_produced = sum(1 for e in eforge.values() if e["model_patch"].strip())
    e_total_time = sum(e["duration_seconds"] for e in eforge.values())
    print(f"\neforge: {e_produced}/{len(eforge)} produced patches, {e_total_time:.0f}s total")

    if baseline:
        b_produced = sum(1 for b in baseline.values() if b["model_patch"].strip())
        b_total_time = sum(b["duration_seconds"] for b in baseline.values())
        print(f"baseline: {b_produced}/{len(baseline)} produced patches, {b_total_time:.0f}s total")


if __name__ == "__main__":
    main()
