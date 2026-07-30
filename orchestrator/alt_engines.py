"""
Both "engines" for claude code and opencode live here.
Can be used as testing against the MCP/tool_loop path.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


def run_claude_code(prompt: str, workspace: Path, timeout: int = 300) -> tuple[str, int]:
    result = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "mcp__sandbox__*"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    output = result.stdout
    if result.stderr:
        output += f"\n---stderr ---\n{result.stderr}"
    return output, result.returncode


def run_opencode(prompt: str, workspace: Path, model: str | None = None, timeout: int = 300) -> tuple[str, int]:
    cmd = ["opencode", "run"]
    if model:
        cmd += (["--model", model])
    cmd.append(prompt)
    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    output = result.stdout
    if result.stderr:
        output += f"\n---stderr ---\n{result.stderr}"
    return output, result.returncode