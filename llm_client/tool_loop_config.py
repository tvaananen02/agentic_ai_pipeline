import re
_PSEUDO_CALL_PATTERN = re.compile(r"<function\((\w+)\)(?:=|\()(\{.*?\})\)?>\s*</function>", re.DOTALL)
MAX_TOOL_RESULT_CHARS = 1500
_CACHEABLE_TOOLS = {"write_file"}
_PYTEST_SUMMARY_PATTERN = re.compile(r"^(=+ .*(passed|failed|error).* =+)$", re.MULTILINE)
_PYTEST_FAILURE_LINE = re.compile(r"^(FAILED|ERROR) (\S+)", re.MULTILINE)
_RATE_LIMIT_WAIT_PATTERN = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)
MAX_RATE_LIMIT_RETRIES = 3