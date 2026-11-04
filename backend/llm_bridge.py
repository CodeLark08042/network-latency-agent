"""DeepSeek transport for the *same* PydanticAI agent used by the CLI.

The CLI bridges PydanticAI to Ollama (``src.agent.make_ollama_function_model``).
The web backend needs a cloud model, so this module provides the same kind of
bridge for DeepSeek's OpenAI-compatible endpoint (``/chat/completions``).

Only the transport changes: system prompt, tool schemas and the 5-round tool
budget all come from ``src.agent`` / ``register_tools``, so the web and CLI
entry points investigate with exactly the same agent.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src.agent import _extract_trace, build_system_prompt, register_tools, to_text
from src.tools import set_active_scenario

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def _to_openai_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Convert PydanticAI message history into OpenAI chat-completion messages."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    converted.append({"role": "system", "content": part.content})
                elif isinstance(part, UserPromptPart):
                    converted.append({"role": "user", "content": to_text(part.content)})
                elif isinstance(part, ToolReturnPart):
                    converted.append({
                        "role": "tool",
                        "tool_call_id": part.tool_call_id or part.tool_name,
                        "content": to_text(part.content),
                    })
                elif isinstance(part, RetryPromptPart):
                    converted.append({"role": "user", "content": to_text(part.content)})
        elif isinstance(message, ModelResponse):
            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for part in message.parts:
                if isinstance(part, TextPart):
                    text_chunks.append(part.content)
                elif isinstance(part, ToolCallPart):
                    tool_calls.append({
                        "id": part.tool_call_id or f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": part.tool_name,
                            "arguments": json.dumps(part.args or {}, ensure_ascii=False),
                        },
                    })
            item: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(chunk for chunk in text_chunks if chunk).strip() or None,
            }
            if tool_calls:
                item["tool_calls"] = tool_calls
            if item["content"] or tool_calls:
                converted.append(item)
    return converted


def _openai_tools(agent_info: AgentInfo) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.parameters_json_schema,
            },
        }
        for tool in agent_info.function_tools
    ]


def make_deepseek_function_model(
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.0,
    max_tool_rounds: int = 5,
    stats: dict[str, Any] | None = None,
) -> FunctionModel:
    """Bridge PydanticAI to DeepSeek's OpenAI-compatible chat API.

    ``max_tool_rounds`` is enforced here, at the model boundary, exactly like the
    Ollama bridge: once the budget is spent the tool schemas are withheld and the
    model is forced to write the final report, so the loop always terminates.
    """
    stats = {} if stats is None else stats

    def run_deepseek(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        from openai import OpenAI  # imported lazily: CLI users do not need it

        client = OpenAI(api_key=api_key, base_url=base_url)

        tool_rounds = stats.get("tool_rounds", 0)
        allow_tools = tool_rounds < max_tool_rounds

        payload_messages = _to_openai_messages(messages)
        if not allow_tools:
            payload_messages.append({
                "role": "user",
                "content": (
                    "工具调用预算已用完。请基于以上所有工具返回的证据，"
                    "立即给出最终调查报告（问题概述、证据分析、结论与建议），不要再调用工具。"
                ),
            })

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": 2048,
        }
        if allow_tools:
            kwargs["tools"] = _openai_tools(agent_info)
            kwargs["tool_choice"] = "auto"

        response = client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        stats["llm_calls"] = stats.get("llm_calls", 0) + 1

        parts: list[TextPart | ToolCallPart] = []
        content = (getattr(message, "content", None) or "").strip()
        if content:
            parts.append(TextPart(content=content))

        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if not allow_tools:
            raw_tool_calls = []
        for raw_call in raw_tool_calls:
            function = raw_call.function
            arguments = function.arguments or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            parts.append(ToolCallPart(
                tool_name=function.name or "",
                args=arguments,
                tool_call_id=raw_call.id or "",
            ))

        stats["tool_rounds"] = tool_rounds + (1 if raw_tool_calls else 0)
        if not parts:
            parts.append(TextPart(content="模型没有返回内容。"))

        return ModelResponse(parts=parts, model_name=model)

    return FunctionModel(function=run_deepseek, model_name=model)


def run_investigation_deepseek(
    prompt: str,
    api_key: str,
    scenario: str = "congestion",
    use_skill: bool = True,
    max_tool_rounds: int = 5,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Run one investigation on the cloud model and return the same shape as the CLI."""
    stats: dict[str, Any] = {}
    agent = Agent(
        model=make_deepseek_function_model(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
            stats=stats,
        ),
        system_prompt=build_system_prompt(use_skill),
        output_type=str,
    )
    register_tools(agent)

    set_active_scenario(scenario)
    result = agent.run_sync(prompt)
    return {
        "output": result.output,
        "trace": _extract_trace(result.all_messages()),
        "stats": stats,
        "scenario": scenario,
        "model": model,
        "source": "deepseek",
    }