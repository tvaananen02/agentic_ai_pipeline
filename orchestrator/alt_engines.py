"""
Both "engines" for claude code and opencode live here.
Can be used as testing against the MCP/tool_loop path.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

def run_claude_code(prompt: str, workspace: Path, timeout: int = 300) -> tuple[str, int]:
    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "allowedTools","mcp__sandbox__*"
        ],
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
        cmd+=(["--model", model])
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


def verify_via_filesystem(workspace: Path, project_name: str) -> tuple[bool, str]:    
    project_dir = workspace / project_name
    solution = project_dir / "solution.py"
    test_file = project_dir / "test_solution.py"
 
    if not solution.exists():
        return False, "solution.py was never created"
    if not test_file.exists():
        return False, "test_solution.py is missing from the project directory"
    try:
        result = subprocess.run(
            ["python3", "-m","pytest", str(test_file), "-v"],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=60,
        )  
    except subprocess.TimeoutExpired:
            return False, "pytest timed out"
    output = result.stdout + result.stderr
    passed = (
        result.returncode == 0
        and "passed" in output.lower()
    )
    return passed, output

def find_project_dir(workspace: Path) -> str | None:
    for entry in workspace.iterdir():
        if entry.is_dir() and (entry / "solution.py").exists() and (entry / "test_solution.py").exists():
            return entry.name
    return None