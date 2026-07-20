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
import httpx
import sys
import threading
import uuid
from mcp.server.fastmcp import FastMCP
from tools import TOOL_SETS, is_tool_allowed
from validation import ValidationError, safe_command, safe_path, safe_url

mcp = FastMCP("sandbox-server")

AGENT_ROLE = os.environ.get("AGENT_ROLE", "")

_background_processes: dict[str, dict] = {}

def _reader_thread(proc, output_buffer):
    for line in proc.stdout:
        output_buffer.append(line)

@mcp._mcp_server.list_tools()
async def filtered_list_tools():
    all_tools = await mcp.list_tools()
    allowed = TOOL_SETS.get(AGENT_ROLE, set())
    return [t for t in all_tools if t.name in allowed]

def require_role(func: Callable) -> Callable:
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

@mcp.tool()
@require_role
def git_commit(message: str) -> str:
    if not message or not message.strip():
        return "ERROR: commit message cannot be empty"
    workspace = os.environ.get("WORKSPACE_ROOT", "/workspace")
    try:
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if add_result.returncode != 0:
            return f"ERROR: git add failed: {add_result.stderr}"

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: git commit timed out"
    except OSError as e:
        return f"ERROR: could not run git: {e}"

    output = commit_result.stdout
    if commit_result.stderr:
        output += f"\n--- stderr ---\n{commit_result.stderr}"
    output += f"\n--- exit code: {commit_result.returncode} ---"
    return output

@mcp.tool()
@require_role
def git_push() -> str:
    workspace = os.environ.get("WORKSPACE_ROOT", "/workspace")
    try:
        result = subprocess.run(
            ["git", "push"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: git push timed out"
    except OSError as e:
        return f"ERROR: could not run git: {e}"

    output = result.stdout
    if result.stderr:
        output += f"\n--- stderr ---\n{result.stderr}"
    output += f"\n--- exit code: {result.returncode} ---"
    return output

@mcp.tool()
@require_role
def http_request(url: str, method: str = "GET", body: str | None = None) -> str:
    method = method.upper()
    try:
        target_url = safe_url(url)
    except ValidationError as e:
        return f"ERROR: {e}"
    headers = {"Content-Type": "application/json"} if body else None
    try:
        response = httpx.request(
            method, target_url, content=body, headers=headers, timeout=30
        )
    except httpx.RequestError as exc:
        return f"ERROR: request failed: {exc}"
    return f"Status: {response.status_code}\n{response.text}"

@mcp.tool()
@require_role
def start_background(command: str) -> str:
    try:
        parts = safe_command(command)
    except ValidationError as e:
        return f"ERROR: {e}"
    workspace = os.environ.get("WORKSPACE_ROOT", "/workspace")
    try:
        proc = subprocess.Popen(
            parts, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
    except OSError as e:
        return f"ERROR: could not start process: {e}"
    process_id = str(uuid.uuid4())[:8]
    output_buffer: list[str] = []
    thread = threading.Thread(target=_reader_thread, args=(proc, output_buffer), daemon=True)
    thread.start()
    _background_processes[process_id] = {"proc": proc, "output": output_buffer}
    return f"Started background process, process_id={process_id}"
 
@mcp.tool()
@require_role
def get_background_output(process_id: str) -> str:
    entry = _background_processes.get(process_id)
    if not entry:
        return f"ERROR: unknown process_id {process_id}"
    running = entry["proc"].poll() is None
    return f"running={running}\n{''.join(entry['output'])}"

@mcp.tool()
@require_role
def stop_background(process_id: str) -> str:
    """Stop a background process started with start_background."""
    entry = _background_processes.get(process_id)
    if not entry:
        return f"ERROR: unknown process_id {process_id}"
    entry["proc"].terminate()
    try:
        entry["proc"].wait(timeout=5)
    except subprocess.TimeoutExpired:
        entry["proc"].kill()
    return f"Stopped {process_id}"

if __name__ == "__main__":
    if not AGENT_ROLE:
        print(
            "WARNING: AGENT_ROLE is not set. All tool calls will be "
            "rejected. Launch with e.g. AGENT_ROLE=se_engineer python server.py",
            file=sys.stderr,
        )
    mcp.run()