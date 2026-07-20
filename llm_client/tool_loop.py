from __future__ import annotations
 
from base import LLMProvider
  
async def run_tool_loop(
    provider: LLMProvider,
    session,
    system_prompt: str,
    user_input: str,
    max_iterations: int = 10,
) -> tuple[str, list[dict]]:
    tools = (await session.list_tools()).tools
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    tools_called: list[dict] = []

    for i in range(max_iterations):
        response = await provider.call(messages, tools)
        if not response.tool_calls:
            return response.text or "", tools_called
        messages.append(provider.format_assistant_message(response))
        for tc in response.tool_calls:
            print(f"  tool_call: {tc.name}({tc.arguments})")
            tools_called.append({"name": tc.name, "arguments": tc.arguments})
            result = await session.call_tool(tc.name, tc.arguments)
            result_text = "".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            print(f"  result: {result_text[:200]}")
            messages.append(provider.format_tool_result_message(tc.id, result_text))

    raise RuntimeError(f"Hit max_iterations ({max_iterations}) without a final answer")
 
