from __future__ import annotations
from base import LLMProvider
import asyncio
import json
import re
import tool_loop_config



def _extract_pseudo_tool_calls(text: str) -> list[dict]:
    calls = []
    for match in tool_loop_config._PSEUDO_CALL_PATTERN.finditer(text):
        name, raw_args = match.group(1), match.group(2)
        try:
            calls.append({"name": name, "arguments": json.loads(raw_args)})
        except json.JSONDecodeError:
            continue
    return calls


def _truncate_for_history(result_text: str, keep_end: bool = False) -> str:
    if len(result_text) <= tool_loop_config.MAX_TOOL_RESULT_CHARS:
        return result_text
    if keep_end:
        return f"... [truncated - {len(result_text)} chars total]\n" + result_text[-tool_loop_config.MAX_TOOL_RESULT_CHARS:]
    return result_text[:tool_loop_config.MAX_TOOL_RESULT_CHARS] + f"\n... [truncated - {len(result_text)} chars total]"


def _compact_pytest_output(raw: str) -> str:
    summary_match = tool_loop_config._PYTEST_SUMMARY_PATTERN.search(raw)
    summary = summary_match.group(1).strip("= ") if summary_match else "no summary line found"
    failures = tool_loop_config._PYTEST_FAILURE_LINE.findall(raw)
    if failures:
        names = ", ".join(f"{kind}: {name}" for kind, name in failures)
        return f"pytest result: {summary}. Failing: {names}"
    return f"pytest result: {summary}"


async def _execute_tool_call(session, name: str, arguments: dict, call_cache: dict, log_fn) -> str:
    cache_key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
    if name in tool_loop_config._CACHEABLE_TOOLS and cache_key in call_cache:
        log_fn(f"  tool_call: {name}({arguments}) [repeated - reusing prior result]")
        return call_cache[cache_key]
    log_fn(f"  tool_call: {name}({arguments})")
    result = await session.call_tool(name, arguments)
    result_text = "".join(block.text for block in result.content if hasattr(block, "text"))
    if name in tool_loop_config._CACHEABLE_TOOLS:
        call_cache[cache_key] = result_text
    return result_text


async def _maybe_auto_test(session, tc_name: str, tc_arguments: dict, call_cache: dict, log_fn, tools_called: list[dict], status_fn=None) -> str | None:
    path = tc_arguments.get("path", "")
    if tc_name != "write_file" or not path.endswith("solution.py") or path.endswith("test_solution.py"):
        return None
    test_path = path[: -len("solution.py")] + "test_solution.py"
    command = f"pytest {test_path}"
    if status_fn:
        status_fn("Running tests automatically...")
    raw_result = await _execute_tool_call(session, "run_command", {"command": command, "timeout_seconds": 60}, call_cache, log_fn)
    log_fn(f"  auto-test raw: {raw_result[:400]}")
    summary = _compact_pytest_output(raw_result)
    log_fn(f"  auto-test: {summary}")
    tools_called.append({"name": "run_command", "arguments": {"command": command}, "result": raw_result})
    return summary


async def _call_with_retry(provider, messages, tools, log_fn, status_fn=None):
    for attempt in range(tool_loop_config.MAX_RATE_LIMIT_RETRIES + 1):
        try:
            if status_fn:
                status_fn("Waiting for model response...")
            return await provider.call(messages, tools)
        except Exception as e:
            error_text = str(e)
            if "rate_limit_exceeded" not in error_text or attempt == tool_loop_config.MAX_RATE_LIMIT_RETRIES:
                raise
            match = tool_loop_config._RATE_LIMIT_WAIT_PATTERN.search(error_text)
            wait_seconds = float(match.group(1)) + 0.5 if match else 10.0
            log_fn(f"  Rate limited, waiting {wait_seconds:.1f}s before retry {attempt + 1}/{tool_loop_config.MAX_RATE_LIMIT_RETRIES}...")
            if status_fn:
                status_fn(f"Rate limited - waiting {wait_seconds:.0f}s (retry {attempt + 1}/{tool_loop_config.MAX_RATE_LIMIT_RETRIES})...")
            await asyncio.sleep(wait_seconds)


async def run_tool_loop(
    provider: LLMProvider,
    session,
    system_prompt: str,
    user_input: str,
    max_iterations: int = 10,
    log_fn=print,
    status_fn=None,
) -> tuple[str, list[dict]]:
    tools = (await session.list_tools()).tools
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    tools_called: list[dict] = []
    call_cache: dict[str, str] = {}

    for i in range(max_iterations):
        if status_fn:
            status_fn(f"[{i + 1}/{max_iterations}] Thinking...")
        try:
            response = await _call_with_retry(provider, messages, tools, log_fn, status_fn)
        except Exception as e:
            log_fn(f"  LLM call failed and could not be recovered: {e}")
            if status_fn:
                status_fn(f"Failed: {e}")
            return f"ERROR: LLM call failed: {e}", tools_called

        if not response.tool_calls:
            recovered = _extract_pseudo_tool_calls(response.text or "")
            if not recovered:
                if status_fn:
                    status_fn("Done.")
                return response.text or "", tools_called

            log_fn(f"  Recovering {len(recovered)} tool call(s) sent as text")
            messages.append({"role": "assistant", "content": response.text})
            for call in recovered:
                if status_fn:
                    status_fn(f"Running {call['name']}...")
                result_text = await _execute_tool_call(session, call["name"], call["arguments"], call_cache, log_fn)
                log_fn(f"  result: {result_text[:200]}")
                auto_test = await _maybe_auto_test(session, call["name"], call["arguments"], call_cache, log_fn, tools_called, status_fn)
                if auto_test:
                    result_text = f"{result_text}. {auto_test}"
                tools_called.append({"name": call["name"], "arguments": call["arguments"], "result": result_text})
                messages.append({
                    "role": "user",
                    "content": f"Result of {call['name']}: {_truncate_for_history(result_text, keep_end=(call['name'] == 'run_command'))}",
                })
            continue

        messages.append(provider.format_assistant_message(response))
        for tc in response.tool_calls:
            if status_fn:
                status_fn(f"Running {tc.name}...")
            result_text = await _execute_tool_call(session, tc.name, tc.arguments, call_cache, log_fn)
            log_fn(f"  result: {result_text[:200]}")
            auto_test = await _maybe_auto_test(session, tc.name, tc.arguments, call_cache, log_fn, tools_called, status_fn)
            if auto_test:
                result_text = f"{result_text}. {auto_test}"
            tools_called.append({"name": tc.name, "arguments": tc.arguments, "result": result_text})
            messages.append(provider.format_tool_result_message(tc.id, _truncate_for_history(result_text, keep_end=(tc.name == "run_command"))))

    log_fn(f"  Hit max_iterations ({max_iterations}) without a final answer")
    if status_fn:
        status_fn(f"Hit iteration limit ({max_iterations}).")
    return f"ERROR: hit max_iterations ({max_iterations}) without a final answer", tools_called