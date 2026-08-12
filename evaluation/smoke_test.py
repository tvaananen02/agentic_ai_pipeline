"""
Fast sanity check that the full pipeline still works end to end, with a
trivial, low-token spec.
Running with command: python3 evaluation/smoke_test.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
from headless_run_script import run_once

SPEC = "a command line tool that checks if a number is prime"

async def main() -> int:
    print(f"Smoke test: running spec {SPEC!r}...")
    succeeded = await run_once(SPEC, run_index=0)
    if succeeded:
        print("\nSmoke test PASSED - pipeline reached a working deployment.")
        return 0
    print("\nSmoke test FAILED - pipeline did not reach deployment. Check the log above.")
    return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))