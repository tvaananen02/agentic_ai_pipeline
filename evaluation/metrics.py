
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
import config

def _load_runs():
    runs = []
    for f in config.RUN_LOGS_DIR.glob("*.json"):
        try:
            runs.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return runs

def _run_succeeded(run: dict) -> bool:
    stages = run.get("stage_results", {})
    if not stages:
        return False
    return all(s.get("approved") for s in stages.values())

def _first_failed_stage(run: dict) -> str | None:
    for role, result in run.get("stage_results", {}).items():
        if not result.get("approved"):
            return role
    return None

def summarize(runs: list[dict]) -> None:
    if not runs:
        print(f"No run logs found in {config.RUN_LOGS_DIR}")
        return
    by_engine_model: dict[tuple[str, str], list[bool]] = defaultdict(list)
    failed_stage_counts: dict[str, int] = defaultdict(int)
    for run in runs:
        engine = run.get("engine", "unknown")
        model = run.get("model", "unknown")
        succeeded = _run_succeeded(run)
        by_engine_model[(engine, model)].append(succeeded)
        if not succeeded:
            stage = _first_failed_stage(run) or "unknown"
            failed_stage_counts[stage] += 1
    print(f"\n{len(runs)} run(s) found in {config.RUN_LOGS_DIR}\n")
    print(f"{'engine':<12} {'model':<28} {'runs':>5} {'success':>8} {'rate':>7}")
    print("-" * 65)
    for (engine, model), results in sorted(by_engine_model.items()):
        total = len(results)
        passed = sum(results)
        rate = f"{passed / total * 100:.0f}%" if total else "n/a"
        print(f"{engine:<12} {model:<28} {total:>5} {passed:>8} {rate:>7}")
    if failed_stage_counts:
        print("\nRejections by stage:")
        for stage, count in sorted(failed_stage_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {stage:<15} {count}")
    print(
        "\nNote: rejection reasons themselves are not currently persisted to the run "
        "log - only approved/rejected per stage. See run_stage_in_session in "
        "pipeline_runner.py if you want to add that later."
    )
if __name__ == "__main__":
    summarize(_load_runs())