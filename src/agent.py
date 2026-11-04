"""Network latency investigation agent built with PydanticAI + Ollama.

The agent investigates network latency issues by:
1. Understanding the reported problem
2. Proposing hypotheses (congestion, route change, hardware fault, etc.)
3. Calling tools to gather evidence
4. Analyzing evidence using networking knowledge
5. Forming conclusions with supporting/refuting evidence
6. Providing actionable recommendations
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import Agent, ModelRetry
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

from .skills import DEFAULT_SKILL, load_skill_prompt
from .tools import (
    tool_get_link_metrics,
    tool_calculate_queue_delay,
    tool_analyze_delay_components,
    tool_list_network,
)


# ---------------------------------------------------------------------------
# Ollama integration (same pattern as course demo)
# ---------------------------------------------------------------------------

RAW_OLLAMA_RESPONSES: list[dict[str, Any]] = []


def clear_proxy_env() -> None:
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
        os.environ.pop(key, None)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a possibly string-formatted number (e.g. '11000 pps') to float."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def build_ollama_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    ollama_messages: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    ollama_messages.append({"role": "system", "content": part.content})
                elif isinstance(part, UserPromptPart):
                    ollama_messages.append({"role": "user", "content": to_text(part.content)})
                elif isinstance(part, ToolReturnPart):
                    ollama_messages.append({
                        "role": "tool",
                        "tool_name": part.tool_name,
                        "content": to_text(part.content),
                    })
                elif isinstance(part, RetryPromptPart):
                    ollama_messages.append({"role": "user", "content": to_text(part.content)})
        elif isinstance(message, ModelResponse):
            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for part in message.parts:
                if isinstance(part, TextPart):
                    text_chunks.append(part.content)
                elif isinstance(part, ToolCallPart):
                    tool_calls.append({
                        "id": part.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": part.tool_name,
                            "arguments": part.args if part.args is not None else {},
                        },
                    })
            if text_chunks or tool_calls:
                item: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(chunk for chunk in text_chunks if chunk).strip(),
                }
                if tool_calls:
                    item["tool_calls"] = tool_calls
                ollama_messages.append(item)
    return ollama_messages


def build_ollama_tools(agent_info: AgentInfo) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in agent_info.function_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.parameters_json_schema,
            },
        })
    return tools


def call_ollama_chat(
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    host: str,
    temperature: float = 0.0,
    think: bool | None = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_name,
        "stream": False,
        "messages": messages,
        "options": {"temperature": temperature, "num_predict": 2048},
        "keep_alive": "30m",
    }
    if think is not None:
        payload["think"] = think
    if tools:
        payload["tools"] = tools

    request = urllib.request.Request(
        host,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    clear_proxy_env()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))
    RAW_OLLAMA_RESPONSES.append(result)
    return result


def make_ollama_function_model(
    model_name: str,
    host: str,
    temperature: float = 0.0,
    think: bool | None = False,
    max_tool_rounds: int = 5,
    stats: dict[str, Any] | None = None,
) -> FunctionModel:
    """Build a FunctionModel bridging PydanticAI to Ollama.

    ``max_tool_rounds`` caps how many times the model is allowed to emit tool
    calls. Once the cap is reached, tool schemas are withheld and the model is
    instructed to produce the final report, guaranteeing termination.
    """
    if stats is None:
        stats = {}

    def run_ollama(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        ollama_messages = build_ollama_messages(messages)
        tool_rounds = stats.get("tool_rounds", 0)
        allow_tools = tool_rounds < max_tool_rounds

        if not allow_tools:
            ollama_messages.append({
                "role": "user",
                "content": (
                    "工具调用预算已用完。请基于以上所有工具返回的证据，"
                    "立即给出最终调查报告（问题概述、证据分析、结论与建议），不要再调用工具。"
                ),
            })

        response = call_ollama_chat(
            model_name=model_name,
            messages=ollama_messages,
            tools=build_ollama_tools(agent_info) if allow_tools else None,
            host=host,
            temperature=temperature,
            think=think,
        )
        message = response.get("message", {})
        parts: list[TextPart | ToolCallPart] = []

        content = (message.get("content") or "").strip()
        if not content:
            content = (message.get("thinking") or "").strip()
        # Qwen3 may inline reasoning; keep only the text after the closing tag.
        if "</think>" in content:
            content = content.split("</think>", 1)[1].strip()
        if content:
            parts.append(TextPart(content=content))

        raw_tool_calls = message.get("tool_calls", []) if allow_tools else []
        for tool_call in raw_tool_calls:
            function = tool_call.get("function", {})
            raw_args = function.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            parts.append(ToolCallPart(
                tool_name=function.get("name", ""),
                args=raw_args,
                tool_call_id=tool_call.get("id", ""),
            ))

        stats["tool_rounds"] = tool_rounds + (1 if raw_tool_calls else 0)
        stats["llm_calls"] = stats.get("llm_calls", 0) + 1

        if not parts:
            parts.append(TextPart(content="模型没有返回内容。"))

        return ModelResponse(parts=parts, model_name=model_name)

    return FunctionModel(function=run_ollama, model_name=f"ollama:{model_name}")


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

# 只包含"怎么用工具"和"怎么输出"的操作性约束，不含任何领域判断知识。
# 专业知识全部放在 Skill（skills/network-latency-investigation/SKILL.md），
# 这样 B 组（无 Skill）与 C 组（有 Skill）的差异才是可归因的。

SYSTEM_PROMPT_BASE = """\
你是一名网络调查 Agent，负责帮助校园网工程师排查网络延迟异常。

## 可用工具

- `list_network`: 查看网络拓扑和可用链路
- `get_link_metrics`: 查询链路实时指标（利用率、RTT、丢包、队列等）
- `analyze_delay_components`: 分解延迟为传播/传输/排队/处理四个部分
- `calculate_queue_delay`: 用 M/M/1 模型计算理论排队延迟

## 调查预算（必须遵守）

- 最多调用 **5 轮** 工具（一轮内可并行调用多个工具）
- 达到 5 轮后，**必须停止调用工具**，直接给出最终报告
- 不要重复调用相同参数的工具

## 输出格式

最终请用中文输出调查报告，包含：
1. 问题概述
2. 调查过程（每一步调用了什么工具，得到了什么结果）
3. 假设分析（每个假设的支持/反驳证据）
4. 结论（最可能的原因，置信度）
5. 建议（可操作的改进措施）

## 底线

- 报告里的所有测量数值必须来自工具返回，不得自己编造
- 工具的返回结果要如实引用，包括缺失或为 null 的字段
"""


def build_system_prompt(use_skill: bool, skill_name: str = DEFAULT_SKILL) -> str:
    """拼装 System Prompt。``use_skill=False`` 时只返回操作约束。"""
    if not use_skill:
        return SYSTEM_PROMPT_BASE
    return SYSTEM_PROMPT_BASE + "\n" + load_skill_prompt(skill_name)


def register_tools(agent: Agent[None, str]) -> None:
    """Register the four investigation tools on an agent.

    Shared by the Ollama CLI agent and the Web backend's DeepSeek agent so the
    two entry points expose exactly the same tool contract.
    """

    @agent.tool_plain
    def list_network() -> dict[str, Any]:
        """List all network links in the simulated campus network.
        Use this first to understand the network topology."""
        return tool_list_network()

    @agent.tool_plain
    def get_link_metrics(
        link_id: Annotated[str, Field(description="Link identifier, e.g. 'link-dist-a-sw1'")],
    ) -> dict[str, Any]:
        """Query the current metrics of a network link: utilization, RTT, packet loss, queue depth and arrival rate."""
        return tool_get_link_metrics(link_id)

    @agent.tool_plain(retries=3)
    def calculate_queue_delay(
        arrival_rate_pps: Annotated[float, Field(description="Packet arrival rate in packets per second (lambda). Pass a plain number, e.g. 11000.")],
        service_rate_pps: Annotated[float, Field(description="Service rate in packets per second (mu) = bandwidth_bps / (packet_bytes*8). Pass a plain number.")],
        avg_packet_size_bytes: Annotated[float, Field(description="Average packet size in bytes (default 800)")] = 800,
        bandwidth_mbps: Annotated[float, Field(description="Link bandwidth in Mbps (default 1000)")] = 1000,
    ) -> dict[str, Any]:
        """Calculate theoretical queue delay using M/M/1 queueing model. Use this to verify if observed delay matches congestion theory."""
        return tool_calculate_queue_delay(
            _as_float(arrival_rate_pps),
            _as_float(service_rate_pps),
            _as_float(avg_packet_size_bytes),
            _as_float(bandwidth_mbps),
        )

    @agent.tool_plain(retries=3)
    def analyze_delay_components(
        link_id: Annotated[str, Field(description="Link identifier to analyze")],
        processing_delay_ms: Annotated[float, Field(description="Estimated router processing delay in ms (default 0.5)")] = 0.5,
    ) -> dict[str, Any]:
        """Decompose total delay on a link into propagation, transmission, queue, and processing components. Use this to identify the dominant delay source."""
        return tool_analyze_delay_components(link_id, None, _as_float(processing_delay_ms))


def build_agent(
    model_name: str,
    host: str,
    temperature: float = 0.0,
    think: bool | None = False,
    use_skill: bool = True,
    max_tool_rounds: int = 5,
    stats: dict[str, Any] | None = None,
) -> Agent[None, str]:
    """Build the network latency investigation agent."""
    model = make_ollama_function_model(
        model_name=model_name,
        host=host,
        temperature=temperature,
        think=think,
        max_tool_rounds=max_tool_rounds,
        stats=stats,
    )

    system_prompt = build_system_prompt(use_skill)

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        output_type=str,
    )
    register_tools(agent)
    return agent


def _extract_trace(messages) -> list[dict[str, Any]]:
    """Extract an ordered tool call / tool return trace from message history."""
    trace: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    trace.append({"tool": part.tool_name, "result": to_text(part.content)})
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    trace.append({"tool_call": part.tool_name, "args": part.args})
    return trace


def run_investigation(
    prompt: str,
    model_name: str = "qwen3:4b",
    host: str = "http://localhost:11434/api/chat",
    temperature: float = 0.0,
    use_skill: bool = True,
    think: bool | None = False,
    max_tool_rounds: int = 5,
) -> dict[str, Any]:
    """Run a network latency investigation and return the result.

    Tool-call rounds are capped by ``max_tool_rounds`` inside the model bridge,
    so the loop always terminates with a written conclusion.
    """
    RAW_OLLAMA_RESPONSES.clear()
    stats: dict[str, Any] = {}
    agent = build_agent(
        model_name=model_name,
        host=host,
        temperature=temperature,
        think=think,
        use_skill=use_skill,
        max_tool_rounds=max_tool_rounds,
        stats=stats,
    )
    degraded = False
    try:
        result = agent.run_sync(prompt)
        messages = result.all_messages()
        output = result.output
        all_messages = json.loads(result.all_messages_json().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - never let a tool failure kill the run
        degraded = True
        output = _fallback_answer(model_name, host, temperature, think, prompt, str(exc))
        messages = []
        all_messages = []

    return {
        "output": output,
        "trace": _extract_trace(messages),
        "raw_responses": RAW_OLLAMA_RESPONSES.copy(),
        "all_messages": all_messages,
        "stats": stats,
        "degraded": degraded,
    }


def _fallback_answer(
    model_name: str,
    host: str,
    temperature: float,
    think: bool | None,
    prompt: str,
    error: str,
) -> str:
    """Produce a conclusion without tools when the agent loop fails."""
    snapshot: dict[str, Any] = {}
    for link in tool_list_network()["links"]:
        metrics = tool_get_link_metrics(link["id"])
        if "error" not in metrics:
            snapshot[link["id"]] = metrics

    messages = [{
        "role": "user",
        "content": (
            "你是校园网工程师。工具调用失败，以下是从监控系统直接取得的当前快照：\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2)}\n\n"
            f"问题：{prompt}\n\n"
            "请基于以上数据给出延迟原因分析与结论，并明确说明证据是否充分。"
        ),
    }]
    try:
        response = call_ollama_chat(
            model_name=model_name, messages=messages, tools=None,
            host=host, temperature=temperature, think=think,
        )
    except Exception:  # noqa: BLE001
        return f"[调查中断] 工具调用失败且无法生成结论：{error}"
    content = (response.get("message", {}).get("content") or "").strip()
    if "</think>" in content:
        content = content.split("</think>", 1)[1].strip()
    return content or f"[调查中断] 工具调用失败：{error}"
