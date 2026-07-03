"""
Maps agent roles to the set of tool names they are allowed to call.
"""

from __future__ import annotations

TOOL_SETS: dict[str, set[str]] = {
    "re_engineer": {"read_file", "write_file", "list_dir"},
    "tester": {"read_file", "write_file", "list_dir"},
    "se_engineer": {
        "read_file", "write_file", "list_dir",
        "run_command",
        "git_commit", "git_push",
        "http_request",
    },
}


def is_tool_allowed(role: str, tool_name: str) -> bool:
    """True if the given agent role may call the given tool."""
    allowed = TOOL_SETS.get(role)
    if allowed is None:
        # Unknown role - fail closed, not open.
        return False
    return tool_name in allowed