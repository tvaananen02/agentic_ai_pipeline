"""
Headless pipeline runner for fast local iteration - no Textual, no manual
clicking through screens. Auto-approves every checkpoint so a full run
(including deploy) completes unattended; auto-rejects still fire exactly
as they do in the TUI, since those come from _validate_stage, not from
this script.

Usage:
    python headless_run.py "a web app with a counter" --engine mcp --model llama-3.3-70b-versatile
    python headless_run.py "a web app with a counter" --engine claude_code
    python headless_run.py "a web app with a counter" --model gpt-oss-120b --runs 5
"""
from __future__ import annotations
import argparse
import asyncio
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config
from pipeline_runner import run_pipeline
from state import PipelineState


async def _auto_approve(role: str, artifact: str, workspace: Path) -> str:
    print(f"[checkpoint: {role}] auto-approved")
    return "approve"


async def run_once(spec: str, run_index: int) -> bool:
    workspace = config.DEMO_PROJECT_DIR / "test_run"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    os.makedirs(config.RUN_LOGS_DIR, exist_ok=True)
    log_path = config.RUN_LOGS_DIR / f"headless_run_{run_index}.json"

    state = PipelineState(
        spec=spec, project_slug="test_run", workspace=str(workspace),
        engine=config.ENGINE, model=getattr(config, "USED_MODEL", config.ENGINE),
    )

    print(f"\n===== run {run_index} | engine={config.ENGINE} model={state.model} =====")
    print(f"spec: {spec}\n")

    try:
        url = await run_pipeline(
            config.ENGINE, spec, workspace, log_path, state,
            checkpoint_fn=_auto_approve, log_fn=print, role_fn=lambda role: print(f"\n--- {role} ---"),
        )
    except Exception:
        crash_log = config.RUN_LOGS_DIR / f"headless_crash_{int(time.time())}.log"
        crash_log.write_text(traceback.format_exc())
        print(f"\nCRASHED - stack trace saved to {crash_log}")
        return False

    if url:
        print(f"\n===== run {run_index}: SUCCESS - {url} =====")
        return True
    print(f"\n===== run {run_index}: did not reach deployment (rejected or no server) =====")
    return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="the plain-language spec to build")
    parser.add_argument("--engine", default=config.ENGINE, choices=["mcp", "claude_code", "opencode"])
    parser.add_argument("--model", default=None, help="Groq model name, e.g. llama-3.3-70b-versatile")
    parser.add_argument("--runs", type=int, default=1, help="repeat N times to gauge success rate")
    args = parser.parse_args()

    config.ENGINE = args.engine
    if args.model:
        config.MODEL_PROFILE = "groq"
        config.USED_MODEL = args.model

    results = []
    for i in range(1, args.runs + 1):
        results.append(await run_once(args.spec, i))

    if args.runs > 1:
        passed = sum(results)
        print(f"\n===== summary: {passed}/{args.runs} runs succeeded =====")


if __name__ == "__main__":
    asyncio.run(main())