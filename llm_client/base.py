from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolCallRequest:
    """One tool call the model wants to make."""
    id: str            # provider-specific call id - needed later to match up the result
    name: str           # tool name, must match an MCP tool name exactly
    arguments: dict      # arguments to pass to session.call_tool()

@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    raw: Any = None      # the original provider response, needed by
                          # format_assistant_message() to reconstruct the
                          # exact message to append to history

class LLMProvider(ABC):
    """Every provider must implement these three methods."""

    @abstractmethod
    async def call(self, messages: list[dict], tools: list) -> LLMResponse:
        ...

    @abstractmethod
    def format_assistant_message(self, response: LLMResponse) -> dict:
        ...

    @abstractmethod
    def format_tool_result_message(self, tool_call_id: str, result_text: str) -> dict:
        ...