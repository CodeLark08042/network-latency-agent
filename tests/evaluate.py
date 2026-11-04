#!/usr/bin/env python3
"""Evaluation harness for the network latency investigation agent.

Three experiment groups are compared on the same cases / model / data:

  A: Direct LLM             (data pasted into prompt, no tools, no skill)
  B: LLM + Agent + Tools    (tools enabled, no skill knowledge)
  C: LLM + Agent + Tools + Skill

Metrics (computed exactly as described below):
  - conclusion_correct : final answer mentions the expected root-cause keywords
  - evidence_completeness : fraction of expected evidence points referenced
  - tool_correctness   : (queried target link) + (used delay analysis) + (used metrics)
  - llm_calls / tool_calls / wall time

Usage:
    python tests/evaluate.py --model qwen3.5:0.8b
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import run_investigation, configure_stdio, clear_proxy_env
from src.tools import (
    set_active_scenario,
    get_active_scenario,
    tool_list_network,
    tool_get_link_metrics,
)

CASES_PATH = Path(__file__).resolve().parent / "cases.json"
RESULTS_DIR = ROOT / "results"
TRACES_DIR = RESULTS_DIR / "traces"


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


# ---------------------------------------------------------------------------
# Group A: direct LLM, no tools
# ---------------------------------------------------------------------------

def run_direct_llm(prompt: str, case: dict, model_name: str, host: str) -> dict[str, Any]:
    """Give the model the raw metrics as text and ask for a conclusion."""
    scenario = case["scenario"]
    set_active_scenario(scenario)

    links = tool_list_network()["links"]
    snapshot = {}
    for link in links:
        snapshot[link["id"]] = tool_get_link_metrics(link["id"])

    context = (
        "你是校园网工程师。当前网络监控快照如下（JSON）：\n"
        f"{json.dumps(snapshot, ensure_ascii=False, indent=2)}\n\n"
        f"问题：{prompt}\n\n"
        "请直接给出你的分析与结论，不要调用任何工具。"
    )

    payload = {
        "model": model_name,
        "stream": False,
        "messages": [{"role": "user", "content": context}],
        "options": {"temperature": 0.0, "num_predict": 2048},
        "think": False,
        "keep_alive": "30m",
    }
    request = urllib.request.Request(
        host,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    clear_proxy_env()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    start = time.time()
    try:
        with opener.open(request, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "output": "", "time_s": round(time.time() - start, 2),
                "llm_calls": 1, "tool_calls": 0, "trace": []}

    content = (result.get("message", {}).get("content") or "")
    if "</think>" in content:
        content = content.split("</think>", 1)[1].strip()

    return {
        "output": content,
        "time_s": round(time.time() - start, 2),
        "llm_calls": 1,
        "tool_calls": 0,
        "trace": [],
    }


# ---------------------------------------------------------------------------
# Groups B / C: agent with tools
# ---------------------------------------------------------------------------

def run_agent(prompt: str, case: dict, model_name: str, host: str, use_skill: bool) -> dict[str, Any]:
    set_active_scenario(case["scenario"])
    start = time.time()
    try:
        result = run_investigation(
            prompt=prompt,
            model_name=model_name,
            host=host,
            use_skill=use_skill,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "output": "", "time_s": round(time.time() - start, 2),
                "llm_calls": 0, "tool_calls": 0, "trace": []}

    trace = result.get("trace", [])
    stats = result.get("stats", {})
    return {
        "output": result["output"],
        "trace": trace,
        "time_s": round(time.time() - start, 2),
        "llm_calls": stats.get("llm_calls", 0),
        "tool_calls": len([t for t in trace if "tool_call" in t]),
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

ROOT_CAUSE_KEYWORDS = {
    "congestion": ["拥塞", "排队", "利用率", "congestion", "queue"],
    "route_change_with_congestion": ["路由", "故障", "切换", "中断", "备用", "failover", "route"],
    "hardware_fault": ["丢包", "硬件", "光模块", "故障", "重传", "packet loss"],
    "congestion_partial_evidence": ["拥塞", "排队", "数据不足", "不完整", "缺失", "无法确定"],
    "normal": ["正常", "无异常", "normal", "指标正常"],
}

# Distinguishing keywords used to check whether the answer lands on the
# *specific* expected cause rather than a generic one.
DISTINGUISHING_KEYWORDS = {
    "congestion": ["拥塞"],
    "route_change_with_congestion": ["路由", "切换", "中断", "备用"],
    "hardware_fault": ["丢包", "光模块", "硬件"],
    "congestion_partial_evidence": ["数据不足", "不完整", "缺失", "无法确定"],
    "normal": ["正常"],
}


def evaluate_conclusion(output: str, case: dict) -> dict[str, Any]:
    """Check whether the conclusion names the expected root cause."""
    expected = case["expected_root_cause"]
    text = output or ""

    generic = [kw for kw in ROOT_CAUSE_KEYWORDS.get(expected, []) if kw in text]
    specific = [kw for kw in DISTINGUISHING_KEYWORDS.get(expected, []) if kw in text]

    return {
        "expected": expected,
        "correct": len(specific) > 0,
        "generic_matched": generic,
        "specific_matched": specific,
    }


def evaluate_tool_usage(trace: list[dict], case: dict) -> dict[str, Any]:
    """Check whether the agent used the right tools and inspected the target link."""
    calls = [t for t in trace if "tool_call" in t]
    target = case["target_link"]

    used_metrics = any(c["tool_call"] == "get_link_metrics" for c in calls)
    used_delay = any(c["tool_call"] == "analyze_delay_components" for c in calls)
    used_queue = any(c["tool_call"] == "calculate_queue_delay" for c in calls)
    checked_target = any(
        str(c.get("args", "")).find(target) >= 0 for c in calls
    )

    # 3 independent criteria; each worth 1/3.
    score = (sum([used_metrics, used_delay, checked_target])) / 3
    return {
        "tool_calls": len(calls),
        "used_metrics": used_metrics,
        "used_delay_analysis": used_delay,
        "used_queue_calc": used_queue,
        "checked_target_link": checked_target,
        "tool_correctness": round(score, 2),
    }


def evaluate_evidence(output: str, case: dict) -> float:
    """Fraction of the case's expected evidence points referenced in the answer."""
    expected = case.get("expected_evidence", [])
    if not expected:
        return 0.0
    text = output or ""
    hit = 0
    for point in expected:
        # An evidence point counts as covered if any of its distinctive tokens appear.
        tokens = [t for t in point.replace(">", " ").replace("~", " ").split() if len(t) >= 2]
        if any(tok in text for tok in tokens):
            hit += 1
    return round(hit / len(expected), 2)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

GROUPS = [
    ("A_LLM_direct", lambda p, c, m, h: run_direct_llm(p, c, m, h)),
    ("B_Agent_Tools", lambda p, c, m, h: run_agent(p, c, m, h, use_skill=False)),
    ("C_Agent_Tools_Skill", lambda p, c, m, h: run_agent(p, c, m, h, use_skill=True)),
]


def run_evaluation(model_name: str, host: str, only: str | None = None) -> list[dict]:
    cases = load_cases()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []

    for case in cases:
        print(f"\n{'=' * 70}")
        print(f"[{case['id']}] {case['name']}  (scenario={case['scenario']})")
        print(f"{'=' * 70}")

        for group_name, fn in GROUPS:
            if only and group_name != only:
                continue
            print(f"  -> {group_name} ...", end=" ", flush=True)
            result = fn(case["prompt"], case, model_name, host)

            conclusion = evaluate_conclusion(result.get("output", ""), case)
            tools = evaluate_tool_usage(result.get("trace", []), case)
            evidence = evaluate_evidence(result.get("output", ""), case)

            row = {
                "case_id": case["id"],
                "case_name": case["name"],
                "scenario": case["scenario"],
                "group": group_name,
                "expected_cause": case["expected_root_cause"],
                "conclusion_correct": conclusion["correct"],
                "specific_matched": "|".join(conclusion["specific_matched"]),
                "evidence_completeness": evidence,
                "tool_correctness": tools["tool_correctness"],
                "tool_calls": result.get("tool_calls", 0),
                "llm_calls": result.get("llm_calls", 0),
                "time_s": result.get("time_s", 0),
                "error": result.get("error", ""),
                "output_chars": len(result.get("output", "") or ""),
            }
            rows.append(row)

            trace_path = TRACES_DIR / f"{case['id']}_{group_name}.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "case_id": case["id"],
                        "group": group_name,
                        "scenario": case["scenario"],
                        "output": result.get("output", ""),
                        "trace": result.get("trace", []),
                        "evaluation": {
                            "conclusion": conclusion,
                            "tools": tools,
                            "evidence_score": evidence,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            flag = "OK  " if conclusion["correct"] else "FAIL"
            print(f"{flag} | evidence={evidence:.0%} | tools={tools['tool_correctness']:.0%} "
                  f"| {result.get('time_s', 0):.0f}s")

    csv_path = RESULTS_DIR / "evaluation.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV saved: {csv_path}")

    summary = summarize(rows)
    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print_summary(summary)
    return rows


def summarize(rows: list[dict]) -> dict[str, Any]:
    groups = ["A_LLM_direct", "B_Agent_Tools", "C_Agent_Tools_Skill"]
    out: dict[str, Any] = {}
    for g in groups:
        sub = [r for r in rows if r["group"] == g]
        if not sub:
            continue
        n = len(sub)
        out[g] = {
            "cases": n,
            "success_rate": round(sum(1 for r in sub if r["conclusion_correct"]) / n, 3),
            "avg_evidence": round(sum(r["evidence_completeness"] for r in sub) / n, 3),
            "avg_tool_correctness": round(sum(r["tool_correctness"] for r in sub) / n, 3),
            "avg_tool_calls": round(sum(r["tool_calls"] for r in sub) / n, 2),
            "avg_llm_calls": round(sum(r["llm_calls"] for r in sub) / n, 2),
            "avg_time_s": round(sum(r["time_s"] for r in sub) / n, 1),
            "errors": sum(1 for r in sub if r["error"]),
        }
    return out


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("EVALUATION SUMMARY")
    print("=" * 78)
    header = f"{'metric':<26}" + "".join(f"| {g:>15} " for g in summary)
    print(header)
    print("-" * len(header))
    metrics = [
        ("task_success_rate", "success_rate"),
        ("avg_evidence", "avg_evidence"),
        ("avg_tool_correctness", "avg_tool_correctness"),
        ("avg_tool_calls", "avg_tool_calls"),
        ("avg_llm_calls", "avg_llm_calls"),
        ("avg_time_s", "avg_time_s"),
        ("errors", "errors"),
    ]
    for label, key in metrics:
        line = f"{label:<26}"
        for g in summary:
            line += f"| {summary[g][key]:>15} "
        print(line)
    print("=" * 78)


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Evaluate the network latency investigation agent")
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--host", default="http://localhost:11434/api/chat")
    parser.add_argument("--only", default=None, choices=["A_LLM_direct", "B_Agent_Tools", "C_Agent_Tools_Skill"],
                        help="Run only one experiment group")
    args = parser.parse_args()

    run_evaluation(args.model, args.host, args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
