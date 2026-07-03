"""
Validation for the tools of the MCP server.
All filesystem and command tools pass through this module before execution for security.
"""
from __future__ import annotations
import os
import shlex
from pathlib import Path

class ValidationError(Exception):
    "Raised when a validation error occurs."

WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace")).resolve()
ALLOWED_COMMANDS: set[str] = {
    "python",
    "python3",
    "pip",
    "pip3",
    "node",
    "npm",
    "npx",
    "pytest",
    "git",
}

def safe_path(user_path: str) -> Path:
    if not user_path or user_path.strip() == "":
        raise ValidationError("Empty path is not allowed.")
    candidate = (WORKSPACE_ROOT / user_path).resolve()
    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValidationError(
            f"The path {user_path} is outside the workspace root. "
            f"Only paths within /workspace are allowed."
        )
    return candidate

def safe_command(command: str) -> list[str]:
    if not command or command.strip() == "":
        raise ValidationError("Empty command is not allowed.")
    try:
        parts = shlex.split(command)
    except ValueError as e:
        raise ValidationError(f"Could not parse command: {e}")

    if not parts:
        raise ValidationError("Empty command is not allowed.")
    executable = parts[0]
    forbidden_chars = {";", "&&", "||", "|", ">", "<", "`", "$("}
    for token in parts:
        if any(fc in token for fc in forbidden_chars):
            raise ValidationError(
                f"The command contains a forbidden character: '{token}'"
            )
    if executable not in ALLOWED_COMMANDS:
        raise ValidationError(
            f"The command '{executable}' is not allowed. "
        )
    return parts
