"""Render real run output into terminal-style PNG screenshots.

The images are faithful renderings of actual captured output files:
  - results/run_demo_console.log    (user input + agent progress)
  - results/investigation_demo.md   (tool calls + evidence + conclusion)

Run: python scripts/make_screenshots.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "screenshots"
DOCS.mkdir(parents=True, exist_ok=True)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "C:/Windows/Fonts/lucon.ttf",
]
CJK_CANDIDATES = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]

BG = (30, 32, 36)
FG = (222, 226, 230)
PROMPT_COLOR = (106, 190, 120)
TOOL_COLOR = (108, 168, 240)
OK_COLOR = (110, 200, 140)
HEAD_COLOR = (240, 200, 110)


def _font(size: int, text: str = ""):
    """Pick a font that can render CJK when needed."""
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if has_cjk:
        for c in CJK_CANDIDATES:
            if Path(c).exists():
                try:
                    return ImageFont.truetype(c, size)
                except OSError:
                    pass
    for c in FONT_CANDIDATES:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                pass
    return ImageFont.load_default()


def render_terminal(lines: list[tuple[str, tuple[int, int, int]]], out_path: Path,
                    title: str = "PowerShell  —  network-latency-agent",
                    font_size: int = 17) -> None:
    pad = 22
    line_h = int(font_size * 1.55)
    title_h = 40

    # Measure each line with the font that will actually render it, so CJK
    # glyph widths are accounted for.
    probe_cache: dict[tuple[int, bool], ImageFont.ImageFont] = {}

    def probe_for(text: str):
        cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        key = (font_size, cjk)
        if key not in probe_cache:
            probe_cache[key] = _font(font_size, text)
        return probe_cache[key]

    max_w = 900
    for text, _ in lines:
        f = probe_for(text)
        try:
            bbox = f.getbbox(text)
        except Exception:  # noqa: BLE001
            bbox = (0, 0, len(text) * font_size // 2, font_size)
        max_w = max(max_w, bbox[2] + pad * 2 + 30)

    width = int(min(max_w, 2000))
    height = pad * 2 + title_h + line_h * len(lines) + 10

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # title bar
    d.rectangle([0, 0, width, title_h], fill=(48, 52, 58))
    d.text((16, 11), title, font=_font(15, title), fill=(200, 205, 212))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([width - 78 + i * 22, 13, width - 66 + i * 22, 25], fill=c)

    y = pad + title_h
    for text, color in lines:
        d.text((pad, y), text, font=_font(font_size, text), fill=color)
        y += line_h

    img.save(out_path)
    print("saved", out_path)


def _disp_width(s: str) -> int:
    """Approximate display width: CJK/fullwidth glyphs count as 2 columns."""
    w = 0
    for ch in s:
        w += 2 if ("\u4e00" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef"
                   or "\u3000" <= ch <= "\u303f") else 1
    return w


def wrap(text: str, width: int = 92) -> list[str]:
    """Wrap by display width so CJK text does not overflow the image."""
    out = []
    for raw in text.splitlines():
        if not raw:
            out.append("")
            continue
        line = ""
        for ch in raw:
            if _disp_width(line + ch) > width:
                out.append(line)
                line = ch
            else:
                line += ch
        out.append(line)
    return out


def screenshot_run_console():
    log = ROOT / "results" / "run_demo_console.log"
    if not log.exists():
        print("missing", log, "- skip screenshot 1")
        return
    raw = log.read_text(encoding="utf-8", errors="replace")
    lines: list[tuple[str, tuple[int, int, int]]] = [
        (r"PS E:\AIagentprog\network-latency-agent> python -m src.main --scenario congestion --prompt \"...\"",
         PROMPT_COLOR),
        ("", FG),
    ]
    for ln in wrap(raw, 96)[:46]:
        color = FG
        if ln.strip().startswith("PS "):
            color = PROMPT_COLOR
        elif "工具" in ln or "步骤" in ln or "->" in ln:
            color = TOOL_COLOR
        elif "#" in ln[:3] or ln.startswith("==="):
            color = HEAD_COLOR
        lines.append((ln, color))
    render_terminal(lines, DOCS / "screenshot_1_agent_run.png",
                    title="PowerShell — 用户输入与 Agent 调查过程")


def screenshot_tool_trace():
    """Compose a faithful but condensed view: tool calls -> key evidence -> conclusion."""
    trace_path = ROOT / "results" / "traces" / "demo.json"
    md = ROOT / "results" / "investigation_demo.md"
    if not trace_path.exists():
        print("missing", trace_path, "- skip screenshot 2")
        return

    data = json.loads(trace_path.read_text(encoding="utf-8"))
    trace = data.get("trace", [])
    out = data.get("output", "")

    lines: list[tuple[str, tuple[int, int, int]]] = [
        ("## 工具调用记录（真实 Trace，节选关键证据）", HEAD_COLOR),
        ("", FG),
    ]

    step = 0
    for item in trace:
        if "tool_call" in item:
            step += 1
            args = json.dumps(item.get("args", {}), ensure_ascii=False)
            lines.append((f"### 步骤 {step}: 调用 {item['tool_call']}  参数: {args}", TOOL_COLOR))
        elif "tool" in item and item["tool"] != "list_network":
            try:
                payload = json.loads(item["result"])
            except (json.JSONDecodeError, TypeError):
                payload = item["result"]

            keep = None
            if item["tool"] == "get_link_metrics" and isinstance(payload, dict):
                keep = {k: payload.get(k) for k in
                        ["link_id", "utilization", "rtt_ms", "packet_loss_percent",
                         "avg_queue_depth", "peak_queue_depth", "arrival_rate_pps"]}
            elif item["tool"] == "analyze_delay_components" and isinstance(payload, dict):
                keep = {"delay_components": payload.get("delay_components"),
                        "comparison": payload.get("comparison"),
                        "queue_note": payload.get("queue_note")}
            elif item["tool"] == "calculate_queue_delay" and isinstance(payload, dict):
                keep = {k: payload.get(k) for k in
                        ["utilization_rho", "avg_queue_length_Lq", "avg_queue_delay_ms_Wq",
                         "is_stable"]}

            text = json.dumps(keep if keep is not None else payload,
                              ensure_ascii=False, indent=1)
            for ln in wrap(text, 92):
                lines.append(("  " + ln, OK_COLOR))
            lines.append(("", FG))

    # conclusion
    idx = out.find("结论")
    conclusion = out[idx:] if idx > 0 else out[-700:]
    lines.append(("### 最终结论（节选）", HEAD_COLOR))
    for ln in wrap(conclusion, 92)[:16]:
        lines.append((ln, FG))

    render_terminal(lines[:60], DOCS / "screenshot_2_tool_trace.png",
                    title="工具调用记录、证据与最终结论（真实 Trace）")


def screenshot_eval():
    log = ROOT / "results" / "eval_console.log"
    if not log.exists():
        print("missing", log, "- skip screenshot 3")
        return
    raw = log.read_text(encoding="utf-8", errors="replace")
    idx = raw.find("EVALUATION SUMMARY")
    section = raw if idx < 0 else raw[max(0, idx - 900):]
    lines: list[tuple[str, tuple[int, int, int]]] = []
    for ln in wrap(section, 96)[-40:]:
        color = HEAD_COLOR if "====" in ln or "EVALUATION" in ln else FG
        lines.append((ln, color))
    render_terminal(lines, DOCS / "screenshot_3_evaluation.png",
                    title="对照实验评测结果汇总")


if __name__ == "__main__":
    screenshot_run_console()
    screenshot_tool_trace()
    screenshot_eval()
