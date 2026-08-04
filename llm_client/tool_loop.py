from __future__ import annotations
from base import LLMProvider
import json
import re

# Some models occasionally emit a tool call as plain text formatted like
# <function(name)={"arg": "val"}></function>. Worth recovering rather
# than discarding, since the model did the actual work correctly.
_PSEUDO_CALL_PATTERN = re.compile(r"<function\((\w+)\)=(\{.*?\})>\s*</function>", re.DOTALL)

# Cap on what gets resent to the model in conversation history per tool
# result.
MAX_TOOL_RESULT_CHARS = 1500


def _extract_pseudo_tool_calls(text: str) -> list[dict]:
    calls = []
    for match in _PSEUDO_CALL_PATTERN.finditer(text):
        name, raw_args = match.group(1), match.group(2)
        try:
            calls.append({"name": name, "arguments": json.loads(raw_args)})
        except json.JSONDecodeError:
            continue
    return calls


def _truncate_for_history(result_text: str) -> str:
    if len(result_text) <= MAX_TOOL_RESULT_CHARS:
        return result_text
    return (
        result_text[:MAX_TOOL_RESULT_CHARS]
        + f"\n... [truncated for context size - {len(result_text)} chars total]"
    )


async def _execute_tool_call(session, name: str, arguments: dict, call_cache: dict, log_fn) -> str:
    cache_key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
    if cache_key in call_cache:
        log_fn(f"  tool_call: {name}({arguments}) [repeated - reusing prior result, not re-executing]")
        return call_cache[cache_key]
    log_fn(f"  tool_call: {name}({arguments})")
    result = await session.call_tool(name, arguments)
    result_text = "".join(block.text for block in result.content if hasattr(block, "text"))
    call_cache[cache_key] = result_text
    return result_text


async def run_tool_loop(
    provider: LLMProvider,
    session,
    system_prompt: str,
    user_input: str,
    max_iterations: int = 10,
    log_fn=print,
) -> tuple[str, list[dict]]:
    tools = (await session.list_tools()).tools
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    tools_called: list[dict] = []
    call_cache: dict[str, str] = {}

    for i in range(max_iterations):
        try:
            response = await provider.call(messages, tools)
        except Exception as e:
            # Covers LLM API failures the provider itself couldn't recover from
            # (e.g. malformed tool-call retries exhausted, rate limits, network).
            log_fn(f"  LLM call failed and could not be recovered: {e}")
            return f"ERROR: LLM call failed: {e}", tools_called

        if not response.tool_calls:
            recovered = _extract_pseudo_tool_calls(response.text or "")
            if not recovered:
                return response.text or "", tools_called

            log_fn(f"  Model emitted tool call(s) as text instead of proper tool_calls - recovering {len(recovered)}")
            messages.append({"role": "assistant", "content": response.text})
            for call in recovered:
                result_text = await _execute_tool_call(session, call["name"], call["arguments"], call_cache, log_fn)
                log_fn(f"  result: {result_text[:200]}")
                tools_called.append({"name": call["name"], "arguments": call["arguments"], "result": result_text})
                messages.append({
                    "role": "user",
                    "content": f"Result of {call['name']}: {_truncate_for_history(result_text)}",
                })
            continue

        messages.append(provider.format_assistant_message(response))
        for tc in response.tool_calls:
            result_text = await _execute_tool_call(session, tc.name, tc.arguments, call_cache, log_fn)
            log_fn(f"  result: {result_text[:200]}")
            tools_called.append({"name": tc.name, "arguments": tc.arguments, "result": result_text})
            messages.append(provider.format_tool_result_message(tc.id, _truncate_for_history(result_text)))

    log_fn(f"  Hit max_iterations ({max_iterations}) without a final answer")
    return f"ERROR: hit max_iterations ({max_iterations}) without a final answer", tools_called