"""Generate the report figures (architecture, workflow, evaluation chart).

All figures are produced from real project data / definitions, not mock-ups.
Run:  python scripts/make_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)

# 由 --run 指定只画某一次实验；为空时聚合所有归档的重复实验。
RUN_LABEL: str | None = None

# --- Chinese font setup (Windows) -------------------------------------------
for candidate in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
    if Path(candidate).exists():
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["axes.unicode_minus"] = False
        break


def _box(ax, x, y, w, h, text, fc="#E8F0FE", ec="#1A73E8", fs=10, bold=False):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.4, edgecolor=ec, facecolor=fc, zorder=2,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, zorder=3,
            fontweight="bold" if bold else "normal", wrap=True)


def _arrow(ax, p1, p2, color="#5F6368", style="-|>"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14,
                                 linewidth=1.3, color=color, zorder=1,
                                 shrinkA=2, shrinkB=2))


def make_architecture():
    fig, ax = plt.subplots(figsize=(9.2, 7.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # User
    _box(ax, 3.4, 9.05, 3.2, 0.62, "校园网工程师\n（CLI / 交互输入）", fc="#FFF4E5", ec="#F29900", fs=10, bold=True)

    # Agent + LLM
    _box(ax, 2.6, 7.55, 4.8, 1.0,
         "AI Agent（PydanticAI）\nLLM: Ollama qwen3.5:0.8b / qwen3:4b",
         fc="#E8F0FE", ec="#1A73E8", fs=10, bold=True)

    # Skill layer
    _box(ax, 0.35, 5.85, 3.1, 1.35,
         "Domain Skill\nnetwork-latency-investigation\nSKILL.md（流程/硬规则）\nreference.md（公式/误判清单）\n由 src/skills.py 加载",
         fc="#E6F4EA", ec="#137333", fs=7.6)

    # Tool selection
    _box(ax, 3.9, 5.95, 2.6, 1.1, "工具选择\nTool Selection\n(LLM 决策)", fc="#F3E8FD", ec="#8430CE", fs=9)

    # Tools
    _box(ax, 6.95, 5.9, 2.7, 1.2,
         "工具层 Tools\nlist_network\nget_link_metrics\nanalyze_delay_components\ncalculate_queue_delay",
         fc="#E8F0FE", ec="#1A73E8", fs=8.2)

    # Models / data
    _box(ax, 0.35, 4.05, 3.1, 1.2,
         "理论模型层\nM/M/1 排队论\n时延分解公式\n传播/传输/排队/处理",
         fc="#FEF7E0", ec="#F9AB00", fs=8.8)

    _box(ax, 3.9, 4.05, 2.6, 1.2,
         "测量数据层\ndata/sample_data.json\n拓扑 + 5 种场景快照",
         fc="#F1F3F4", ec="#5F6368", fs=8.8)

    _box(ax, 6.95, 4.05, 2.7, 1.2,
         "理论计算\n（确定性程序）\nρ / Lq / Wq\n延迟分解",
         fc="#F1F3F4", ec="#5F6368", fs=8.8)

    # Evidence
    _box(ax, 3.2, 2.75, 4.0, 0.85, "证据分析与假设验证\n支持证据 / 反面证据 / 不确定性",
         fc="#FCE8E6", ec="#C5221F", fs=9.5, bold=True)

    # Output
    _box(ax, 3.2, 1.55, 4.0, 0.85, "调查结论 + 行动建议\n（含置信度与证据引用）",
         fc="#FFF4E5", ec="#F29900", fs=9.5, bold=True)

    # arrows
    _arrow(ax, (5.0, 9.05), (5.0, 8.55))
    _arrow(ax, (3.9, 7.9), (3.45, 7.2))       # agent -> skill
    _arrow(ax, (5.2, 7.55), (5.2, 7.05))      # agent -> tool selection
    _arrow(ax, (6.5, 6.5), (6.95, 6.5))       # selection -> tools
    _arrow(ax, (3.45, 5.85), (2.0, 5.25))     # skill -> models
    _arrow(ax, (5.2, 5.95), (5.2, 5.25))      # selection -> data
    _arrow(ax, (7.0, 5.9), (8.2, 5.25))       # tools -> computation
    _arrow(ax, (1.9, 4.05), (3.6, 3.6))       # models -> evidence
    _arrow(ax, (5.2, 4.05), (5.2, 3.6))       # data -> evidence
    _arrow(ax, (8.3, 4.05), (6.9, 3.6))       # computation -> evidence
    _arrow(ax, (5.2, 2.75), (5.2, 2.4))       # evidence -> conclusion

    ax.text(0.15, 0.35,
            "注：蓝色为 Agent/工具层，绿色为 Skill 知识层，黄色为理论模型层，灰色为数据与确定性计算。",
            fontsize=8, color="#5F6368")

    fig.savefig(DOCS / "architecture.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", DOCS / "architecture.png")


def make_workflow():
    steps = [
        ("1. 接收 Incident\n链路 RTT 5ms → 85ms", "#E8F0FE"),
        ("2. 提出假设\n拥塞 / 路由变更 / 硬件故障", "#E6F4EA"),
        ("3. list_network\n获取拓扑（6 条链路）", "#F3E8FD"),
        ("4. get_link_metrics\n利用率 92%，队列 450，丢包 0.5%", "#F3E8FD"),
        ("5. analyze_delay_components\n排队 0.96ms，实测 RTT 85ms", "#F3E8FD"),
        ("6. calculate_queue_delay\nM/M/1 验证拥塞量级", "#F3E8FD"),
        ("7. 证据分析\n支持：高利用率+大队列\n限制：理论值远小于实测", "#FCE8E6"),
        ("8. 结论与建议\n拥塞为主因，建议限速/扩容", "#FFF4E5"),
    ]
    fig, ax = plt.subplots(figsize=(7.4, 9.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(steps) * 1.22 + 0.4)
    ax.axis("off")

    top = len(steps) * 1.22
    for i, (text, color) in enumerate(steps):
        y = top - i * 1.22 - 1.0
        _box(ax, 1.5, y, 7.0, 0.92, text, fc=color, ec="#5F6368", fs=8.8)
        if i < len(steps) - 1:
            _arrow(ax, (5.0, y), (5.0, y - 0.30))

    fig.savefig(DOCS / "workflow.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", DOCS / "workflow.png")


def _load_runs():
    """Load independent repeat runs.

    ``results/repeat/<label>/summary.json`` are the archived repetitions.
    ``results/summary.json`` is the *latest* run and would duplicate one of
    them, so it is only used when no archived repetitions exist.

    ``RUN_LABEL`` (set by ``--run``) restricts the chart to a single run, which
    is required when two runs used different Skill versions: averaging across
    versions would compare apples with oranges.
    """
    repeat = ROOT / "results" / "repeat"
    runs = []
    if RUN_LABEL:
        p = repeat / RUN_LABEL / "summary.json"
        if not p.exists():
            raise SystemExit(f"找不到 {p}")
        return [json.loads(p.read_text(encoding="utf-8"))]
    if repeat.exists():
        for sub in sorted(repeat.iterdir()):
            p = sub / "summary.json"
            if p.exists():
                runs.append(json.loads(p.read_text(encoding="utf-8")))
    if not runs:
        main = ROOT / "results" / "summary.json"
        if main.exists():
            runs.append(json.loads(main.read_text(encoding="utf-8")))
    return runs


def _mean_range(runs, group, key):
    vals = [r[group][key] for r in runs if group in r and key in r[group]]
    if not vals:
        return 0.0, 0.0, 0.0
    mean = sum(vals) / len(vals)
    return mean, min(vals), max(vals)


def make_eval_chart():
    runs = _load_runs()
    if not runs:
        print("no summary.json, skipping eval chart")
        return

    groups = [g for g in ["A_LLM_direct", "B_Agent_Tools", "C_Agent_Tools_Skill"]
              if any(g in r for r in runs)]
    labels = {"A_LLM_direct": "A: LLM\n直接问答",
              "B_Agent_Tools": "B: Agent\n+Tools",
              "C_Agent_Tools_Skill": "C: Agent+Tools\n+Skill"}

    metrics = [
        ("任务成功率", "success_rate", "#1A73E8"),
        ("证据完整度", "avg_evidence", "#137333"),
        ("工具调用正确率", "avg_tool_correctness", "#F29900"),
    ]

    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    n = len(metrics)
    width = 0.26
    xs = list(range(len(groups)))
    for i, (name, key, color) in enumerate(metrics):
        means, errs = [], []
        for g in groups:
            m, lo, hi = _mean_range(runs, g, key)
            means.append(m)
            errs.append(max(hi - m, m - lo))
        offsets = [x + (i - (n - 1) / 2) * width for x in xs]
        bars = ax.bar(offsets, means, width=width, label=name, color=color, alpha=0.9,
                      yerr=errs, capsize=3, error_kw={"ecolor": "#444", "lw": 0.9})
        for b, v in zip(bars, means):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.035, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=8.5)

    ax.set_xticks(xs)
    ax.set_xticklabels([labels.get(g, g) for g in groups], fontsize=10)
    ax.set_ylim(0, 1.22)
    ax.set_ylabel("得分（0–1）", fontsize=10)
    ax.set_title(
        f"三组对照实验结果（5 个案例，{'单次运行 ' + RUN_LABEL if RUN_LABEL else str(len(runs)) + ' 次重复的均值与波动范围'}）",
        fontsize=11.5,
    )
    ax.legend(fontsize=9, loc="upper left", ncol=3)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)

    fig.savefig(DOCS / "evaluation_chart.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", DOCS / "evaluation_chart.png")


def make_cost_chart():
    runs = _load_runs()
    if not runs:
        return
    groups = [g for g in ["A_LLM_direct", "B_Agent_Tools", "C_Agent_Tools_Skill"]
              if any(g in r for r in runs)]
    short = {"A_LLM_direct": "A: LLM", "B_Agent_Tools": "B: Agent+Tools",
             "C_Agent_Tools_Skill": "C: Agent+Tools+Skill"}
    labels = [short.get(g, g) for g in groups]

    t = [_mean_range(runs, g, "avg_time_s")[0] for g in groups]
    c = [_mean_range(runs, g, "avg_llm_calls")[0] for g in groups]

    fig, ax1 = plt.subplots(figsize=(8.0, 4.3))
    bars = ax1.bar(labels, t, color="#1A73E8", alpha=0.85, width=0.5, label="平均耗时 (s)")
    for b, v in zip(bars, t):
        ax1.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.1f}s", ha="center", fontsize=9)
    ax1.set_ylabel("平均耗时 (秒)", fontsize=10)
    ax1.set_ylim(0, max(t) * 1.3 if t else 1)

    ax2 = ax1.twinx()
    ax2.plot(labels, c, color="#C5221F", marker="o", linewidth=2, label="平均 LLM 调用次数")
    for i, v in enumerate(c):
        ax2.annotate(f"{v:.1f}", (i, v), textcoords="offset points", xytext=(0, 9),
                     ha="center", fontsize=9, color="#C5221F")
    ax2.set_ylabel("平均 LLM 调用次数", fontsize=10)
    ax2.set_ylim(0, max(c) * 1.4 if c else 1)

    ax1.set_title("执行成本对比（耗时 vs. LLM 调用次数）", fontsize=12)
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    ax1.set_axisbelow(True)

    fig.savefig(DOCS / "cost_chart.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", DOCS / "cost_chart.png")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成报告图表")
    parser.add_argument("--run", default=None,
                        help="只使用 results/repeat/<run> 这一次实验的数据，例如 run4")
    args = parser.parse_args()
    RUN_LABEL = args.run

    make_architecture()
    make_workflow()
    make_eval_chart()
    make_cost_chart()
