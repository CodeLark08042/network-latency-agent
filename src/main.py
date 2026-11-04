#!/usr/bin/env python3
"""CLI entry point for the network latency investigation agent.

Usage:
    python -m src.main --prompt "某链路延迟从20ms上升到180ms，请调查原因"
    python -m src.main --interactive
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import run_investigation, configure_stdio, RAW_OLLAMA_RESPONSES
from .tools import set_active_scenario


DEFAULT_PROMPT = (
    "校园网工程师报告：从汇聚路由器A到接入交换机1号（link-dist-a-sw1）的路径"
    "出现严重延迟，用户反馈网页加载缓慢。请调查这条链路的延迟来源，"
    "分析是拥塞、路由变化还是其他原因，并给出建议。"
)

MODEL_PRESETS = {
    "small": "qwen3.5:0.8b",
    "full": "qwen3:4b",
}


def write_report(
    report_path: Path,
    model: str,
    prompt: str,
    result: dict,
    use_skill: bool,
) -> Path:
    """Write investigation report to a markdown file."""
    lines = [
        "# 网络延迟调查报告",
        "",
        "## 配置信息",
        "",
        f"- 模型: `{model}`",
        f"- 使用 Skill: {'是' if use_skill else '否'}",
        "",
        "## 调查问题",
        "",
        prompt,
        "",
        "## 调查结论",
        "",
        result["output"],
        "",
        "## 工具调用记录",
        "",
    ]

    for i, entry in enumerate(result.get("trace", []), 1):
        if "tool_call" in entry:
            lines.append(f"### 步骤 {i}: 调用 {entry['tool_call']}")
            lines.append(f"参数: `{json.dumps(entry.get('args', {}), ensure_ascii=False)}`")
            lines.append("")
        elif "tool" in entry:
            lines.append(f"**工具 {entry['tool']} 返回:**")
            lines.append("")
            try:
                data = json.loads(entry["result"])
                lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```")
            except (json.JSONDecodeError, TypeError):
                lines.append(f"```\n{entry['result']}\n```")
            lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def interactive_mode(args: argparse.Namespace) -> int:
    """Run in interactive mode."""
    model_name = args.model or MODEL_PRESETS[args.model_preset]
    print("=" * 60)
    print("  校园网延迟调查 Agent")
    print("  输入网络问题，Agent 将自动调查并给出分析报告")
    print("  输入 'quit' 或 'exit' 退出")
    print("=" * 60)
    print()

    while True:
        try:
            prompt = input("请输入网络问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            return 0

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("再见！")
            return 0

        print(f"\n正在调查... (模型: {model_name})\n")
        print("-" * 40)

        try:
            result = run_investigation(
                prompt=prompt,
                model_name=model_name,
                host=args.host,
                temperature=args.temperature,
                use_skill=not args.no_skill,
                think=args.think,
            )
        except Exception as exc:
            print(f"调查失败: {exc}")
            continue

        print(result["output"])
        print("-" * 40)
        print(f"共调用 {len([t for t in result.get('trace', []) if 'tool_call' in t])} 次工具")
        print()

    return 0


def single_run(args: argparse.Namespace) -> int:
    """Run a single investigation."""
    model_name = args.model or MODEL_PRESETS[args.model_preset]
    prompt = args.prompt

    print(f"正在调查... (模型: {model_name})\n")

    try:
        result = run_investigation(
            prompt=prompt,
            model_name=model_name,
            host=args.host,
            temperature=args.temperature,
            use_skill=not args.no_skill,
            think=args.think,
        )
    except Exception as exc:
        print(f"调查失败: {exc}", file=sys.stderr)
        return 2

    print("\n" + "=" * 60)
    print("调查结果")
    print("=" * 60)
    print(result["output"])
    print("=" * 60)
    print(f"共调用 {len([t for t in result.get('trace', []) if 'tool_call' in t])} 次工具")

    # Write report
    report_path = Path(args.output)
    write_report(
        report_path=report_path,
        model=model_name,
        prompt=prompt,
        result=result,
        use_skill=not args.no_skill,
    )
    print(f"\n报告已保存至: {report_path}")

    # Save trace
    if args.save_trace:
        trace_path = Path(args.save_trace)
        trace_data = {
            "model": model_name,
            "prompt": prompt,
            "use_skill": not args.no_skill,
            "trace": result.get("trace", []),
            "output": result["output"],
        }
        trace_path.write_text(json.dumps(trace_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"调用记录已保存至: {trace_path}")

    return 0


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(
        description="Network latency investigation agent"
    )
    parser.add_argument("--model", default=None, help="Ollama model name")
    parser.add_argument("--model-preset", choices=sorted(MODEL_PRESETS), default="full")
    parser.add_argument("--host", default="http://localhost:11434/api/chat")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--no-skill", action="store_true", help="Disable skill knowledge in system prompt")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--scenario", default="congestion",
                        choices=["normal", "congestion", "route_change", "packet_loss", "incomplete_data"],
                        help="Simulated live network state")
    parser.add_argument("--output", default="results/investigation_report.md")
    parser.add_argument("--save-trace", default=None, help="Path to save tool call trace JSON")

    args = parser.parse_args()

    set_active_scenario(args.scenario)

    if args.interactive:
        return interactive_mode(args)
    else:
        return single_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
