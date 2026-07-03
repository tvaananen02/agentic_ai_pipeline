"""
sandbox_server - one shared MCP server inside the Docker sandbox

Startup (stdio transport, default):
    AGENT_ROLE=se_engineer python server.py

Testing with MCP Inspector:
    AGENT_ROLE=se_engineer npx @modelcontextprotocol/inspector python server.py
"""
from __future__ import annotations
import functools
import os
import subprocess
from typing import Callable
from mcp.server.fastmcp import FastMCP
from tools import is_tool_allowed
from validation import ValidationError, safe_command, safe_path

mcp = FastMCP("sandbox-server")

AGENT_ROLE = os.environ.get("AGENT_ROLE", "")

def require_role(func: Callable) -> Callable:
    """
    Wraps a tool function so it is rejected up front if the role this
    server process was launched with is not permitted to call it - this
    runs BEFORE any filesystem or subprocess access happens.
    """
    tool_name = func.__name__

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not AGENT_ROLE:
            return "ERROR: server started without AGENT_ROLE set - refusing all tool calls"
        if not is_tool_allowed(AGENT_ROLE, tool_name):
            return (
                f"ERROR: role '{AGENT_ROLE}' is not permitted to call "
                f"'{tool_name}'"
            )
        return func(*args, **kwargs)
    return wrapper

@mcp.tool()
@require_role
def read_file(path: str) -> str:
    """
    Read a file from inside the workspace directory.
    Args:
        path: Path relative to the workspace root, e.g. "src/board.py"
    Returns:
        File contents as text.
    """
    try:
        target = safe_path(path)
    except ValidationError as e:
        return f"ERROR: {e}"
    if not target.exists():
        return f"ERROR: file not found: {path}"
    if not target.is_file():
        return f"ERROR: path is not a file: {path}"

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"ERROR: file is not text (binary data): {path}"

@mcp.tool()
@require_role
def write_file(path: str, content: str) -> str:
    """
    Write a file inside the workspace directory. Creates parent
    directories as needed. Overwrites an existing file.
    Args:
        path: Path relative to the workspace root, e.g. "src/board.py"
        content: Content to write to the file.
    Returns:
        Confirmation message or error.
    """
    try:
        target = safe_path(path)
    except ValidationError as e:
        return f"ERROR: {e}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"ERROR: write failed: {e}"

    return f"Written: {path} ({len(content)} chars)"

@mcp.tool()
@require_role
def list_dir(path: str = ".") -> str:
    """
    List the contents of a directory inside the workspace root.
    Args:
        path: Path relative to the workspace root. Default "." (root).
    Returns:
        Newline-separated list of files and subdirectories. Directories
        are suffixed with "/".
    """
    try:
        target = safe_path(path)
    except ValidationError as e:
        return f"ERROR: {e}"

    if not target.exists():
        return f"ERROR: directory not found: {path}"
    if not target.is_dir():
        return f"ERROR: path is not a directory: {path}"

    entries = sorted(target.iterdir(), key=lambda p: p.name)
    if not entries:
        return "(empty directory)"

    lines = []
    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines)

@mcp.tool()
@require_role
def run_command(command: str, timeout_seconds: int = 60) -> str:
    """
    Args:
        command: The full command line, e.g. "pytest tests/"
        timeout_seconds: Kill the process if it runs longer than this.

    Returns:
        Combined stdout/stderr and the exit code.
    """
    try:
        parts = safe_command(command)
    except ValidationError as e:
        return f"ERROR: {e}"

    try:
        result = subprocess.run(
            parts,
            cwd=os.environ.get("WORKSPACE_ROOT", "/workspace"),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout_seconds}s: {command}"
    except OSError as e:
        return f"ERROR: could not run command: {e}"

    output = result.stdout
    if result.stderr:
        output += f"\n--- stderr ---\n{result.stderr}"
    output += f"\n--- exit code: {result.returncode} ---"
    return output

if __name__ == "__main__":
    if not AGENT_ROLE:
        print(
            "WARNING: AGENT_ROLE is not set. All tool calls will be "
            "rejected. Launch with e.g. AGENT_ROLE=se_engineer python server.py"
        )
    mcp.run()