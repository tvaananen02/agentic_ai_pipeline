"""
Validation for the tools of the MCP server.
All filesystem and command tools pass through this module before execution for security.
"""
from __future__ import annotations
import os
import shlex
from pathlib import Path
from urllib.parse import urlparse
class ValidationError(Exception):
    "Raised when a validation error occurs."

WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace")).resolve()
ALLOWED_COMMANDS: set[str] = {
    "python",
    "python3",
    "pytest",
}

WHITELISTED_DOMAINS: set[str] = {
    "localhost",
    "onrender.com"
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
    
def safe_url(url: str):
    if not url or url.strip() =="":
        raise ValidationError("Empty url is not allowed")
    try:
        parsed_url = urlparse(url)
    except ValueError as e:
        raise ValidationError(f"Could not parse url: {e}")
    
    if parsed_url.scheme not in {"http", "https"}:
        raise ValidationError(
            f"The url {url} is not valid"
        )
    if not parsed_url.hostname:
        raise ValidationError(f"The url {url} does not have a hostname")
    hostname = parsed_url.hostname.lower()
    is_valid_domain = any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in WHITELISTED_DOMAINS
    )
    if not is_valid_domain:
        raise ValidationError(f"The domain {hostname} is not included in the allowed domains ")
    return parsed_url.geturl()  