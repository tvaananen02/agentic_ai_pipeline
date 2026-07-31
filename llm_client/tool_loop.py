from __future__ import annotations
from base import LLMProvider
import json


async def run_tool_loop(
    provider: LLMProvider,
    session,
    system_prompt: str,
    user_input: str,
    max_iterations: int = 10,
    log_fn=print
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
            log_fn(f"  LLM call failed and could not be recovered: {e}")
            return f"ERROR: LLM call failed: {e}", tools_called
        if not response.tool_calls:
            return response.text or "", tools_called
        messages.append(provider.format_assistant_message(response))

        for tc in response.tool_calls:
            cache_key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
            if cache_key in call_cache:
                log_fn(f"  tool_call: {tc.name}({tc.arguments}) [repeated - reusing prior result, not re-executing]")
                result_text = call_cache[cache_key]
            else:
                log_fn(f"  tool_call: {tc.name}({tc.arguments})")
                result = await session.call_tool(tc.name, tc.arguments)
                result_text = "".join(
                    block.text for block in result.content if hasattr(block, "text")
                )
                call_cache[cache_key] = result_text
            log_fn(f"  result: {result_text[:200]}")
            tools_called.append({"name": tc.name, "arguments": tc.arguments, "result": result_text})
            messages.append(provider.format_tool_result_message(tc.id, result_text))

    log_fn(f"  Hit max_iterations ({max_iterations}) without a final answer")
    return f"ERROR: hit max_iterations ({max_iterations}) without a final answer", tools_called