"""Deterministic offline fallback for the web backend.

Used when no DeepSeek API key is configured (or when the cloud call fails), so the
demo still shows real tool output instead of a fabricated LLM paragraph. The text
is produced by fixed rules over the *actual* tool returns, and the response is
clearly labelled ``source="mock"`` in both the API and the UI.
"""

from __future__ import annotations

import json
from typing import Any

from src.tools import set_active_scenario, tool_get_link_metrics, tool_list_network

_DISPLAY_FIELDS = (
    "link_id", "utilization", "rtt_ms", "packet_loss_percent",
    "avg_queue_depth", "arrival_rate_pps",
)


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def _judge(rows: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Return (root_cause, confidence, rationale) from rule evaluation."""
    measured = [r for r in rows if r.get("rtt_ms") is not None]
    if not measured:
        return ("数据不足", "低", "所有链路的关键指标均为 null，无法据此判断根因。")
    lossy = [r for r in measured if (r.get("packet_loss_percent") or 0) >= 1.0]
    loaded = [r for r in measured if (r.get("utilization") or 0) >= 0.8]
    baseline = min((r.get("rtt_ms") or 0) for r in measured) or 1.0
    worst = max(measured, key=lambda r: (r.get("rtt_ms") or 0))

    if lossy and not loaded:
        return (
            "物理层/硬件故障（高丢包 + 低利用率）",
            "中",
            f"{lossy[0]['link_id']} 丢包率 {_fmt(lossy[0].get('packet_loss_percent'))}%，"
            f"但利用率仅 {_fmt((lossy[0].get('utilization') or 0) * 100, 0)}%，"
            "说明延迟来自重传而非排队拥塞。",
        )
    if loaded:
        return (
            "链路拥塞导致排队延迟升高",
            "中",
            f"{loaded[0]['link_id']} 利用率 {_fmt((loaded[0].get('utilization') or 0) * 100, 0)}%，"
            f"RTT {_fmt(loaded[0].get('rtt_ms'))} ms，是实测最低 RTT 的 "
            f"{_fmt((loaded[0].get('rtt_ms') or 0) / baseline, 1)} 倍。",
        )
    if (worst.get("rtt_ms") or 0) >= baseline * 3:
        return (
            "待确认（RTT 异常但指标未超阈值）",
            "低",
            f"{worst['link_id']} 的 RTT 为最低值的 "
            f"{_fmt((worst.get('rtt_ms') or 0) / baseline, 1)} 倍，但利用率与丢包均正常，"
            "需要更多采样或检查路由与配置。",
        )
    return ("未发现异常", "高", "所有有数据链路的利用率、RTT 与丢包率均在正常范围。")


def build_mock_result(scenario: str, prompt: str = "") -> dict[str, Any]:
    """Build an evidence-backed report without calling any large language model."""
    set_active_scenario(scenario)
    trace: list[dict[str, Any]] = []

    links = tool_list_network()["links"]
    trace.append({"tool_call": "list_network", "args": {}})
    trace.append({"tool": "list_network", "result": json.dumps({"links": links}, ensure_ascii=False)})

    rows: list[dict[str, Any]] = []
    for link in links:
        metrics = tool_get_link_metrics(link["id"])
        trace.append({"tool_call": "get_link_metrics", "args": {"link_id": link["id"]}})
        trace.append({"tool": "get_link_metrics", "result": json.dumps(metrics, ensure_ascii=False)})
        if "error" not in metrics:
            rows.append(metrics)

    root_cause, confidence, rationale = _judge(rows)

    table = ["| 链路 | 利用率 | RTT (ms) | 丢包率 (%) | 队列深度 |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        table.append(
            f"| `{row['link_id']}` | {_fmt((row.get('utilization') or 0) * 100, 0)}% | "
            f"{_fmt(row.get('rtt_ms'))} | {_fmt(row.get('packet_loss_percent'))} | "
            f"{_fmt(row.get('avg_queue_depth'), 0)} |"
        )

    output = f"""## 校园网延迟调查报告（离线规则模式）

> 本次结果**不是大模型生成**：后端未配置 `DEEPSEEK_API_KEY`，因此返回基于工具的规则判读。
> 配置密钥后，同一套工具会交给 DeepSeek 完成假设—取证—结论全过程。

### 1. 问题概述

- 用户描述：{prompt or "（未提供）"}
- 当前模拟场景：`{scenario}`
- 已检查链路数：{len(rows)} / {len(links)}

### 2. 证据（来自工具 `list_network` + `get_link_metrics`）

{chr(10).join(table)}

### 3. 结论

- 最可能原因：**{root_cause}**
- 置信度：{confidence}
- 依据：{rationale}

### 4. 建议

1. 对上述异常链路持续采样 5 分钟，确认指标是持续异常还是瞬时抖动。
2. 若为拥塞：检查 QoS 队列与带宽扩容；若为丢包：检查光模块与端口 CRC 计数。
3. 配置 `DEEPSEEK_API_KEY` 后重新运行，可获得带假设检验与完整推理链的报告。
"""

    return {
        "output": output,
        "trace": trace,
        "stats": {"tool_rounds": 1, "llm_calls": 0},
        "scenario": scenario,
        "model": "rule-based-fallback",
        "source": "mock",
    }