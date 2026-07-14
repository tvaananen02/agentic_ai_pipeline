from __future__ import annotations
import json
import openai
from openai import AsyncOpenAI
from base import LLMProvider, LLMResponse, ToolCallRequest

class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, model: str, base_url: str, api_key: str = "not-needed", max_retries: int = 2):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries

    def _convert_tools(self, mcp_tools: list) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in mcp_tools
        ]


    async def call(self, messages: list[dict], tools: list) -> LLMResponse:
        kwargs = {"model": self.model, "messages": list(messages)}
        openai_tools = self._convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
 
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(**kwargs)
                break
            except openai.BadRequestError as e:
                code = (e.body or {}).get("error", {}).get("code")
                if code != "tool_use_failed" or attempt == self.max_retries:
                    raise
                print(f"  [retry {attempt + 1}/{self.max_retries}] malformed tool call, asking model to retry")
                kwargs["messages"] = kwargs["messages"] + [
                    {"role": "user", "content": "Your last tool call was malformed. Call the tool again using the correct function-calling format, with arguments as a separate JSON object, not embedded in the tool name."}
                ]
 
        message = response.choices[0].message
 
        tool_calls = [
            ToolCallRequest(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments),
            )
            for tc in (message.tool_calls or [])
        ]
 
        return LLMResponse(text=message.content, tool_calls=tool_calls, raw=message)


    def format_assistant_message(self, response: LLMResponse) -> dict:
        msg = {"role": "assistant", "content": response.raw.content}
        if response.raw.tool_calls:
            msg["tool_calls"] = [tc.model_dump() for tc in response.raw.tool_calls]
        return msg

    def format_tool_result_message(self, tool_call_id: str, result_text: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": result_text}