"""Build docs/demo-data.json for the static (GitHub Pages) demo.

The static page cannot call the backend, so it replays traces that were really
produced by the CLI experiments. Source of truth: ``results/repeat/run4``.

    python scripts/build_demo_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUN_DIR = BASE_DIR / "results" / "repeat" / "run4" / "traces"
CASES_PATH = BASE_DIR / "tests" / "cases.json"
DATA_PATH = BASE_DIR / "data" / "sample_data.json"
OUT_PATH = BASE_DIR / "docs" / "demo-data.json"

GROUP = "C_Agent_Tools_Skill"
MODEL = "qwen3.5:0.8b"


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    network = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    traces: dict[str, dict] = {}
    for case in cases:
        trace_path = RUN_DIR / f"{case['id']}_{GROUP}.json"
        if not trace_path.exists():
            print(f"[skip] missing {trace_path.name}")
            continue
        record = json.loads(trace_path.read_text(encoding="utf-8"))
        traces[case["id"]] = {
            "output": record.get("output", ""),
            "trace": record.get("trace", []),
            "evaluation": record.get("evaluation", {}),
            "group": record.get("group", GROUP),
            "scenario": record.get("scenario", case["scenario"]),
            "model": MODEL,
        }

    payload = {
        "generated_from": "results/repeat/run4",
        "group": GROUP,
        "model": MODEL,
        "cases": cases,
        "network": {
            "topology": network["topology"],
            "scenarios": {
                name: {
                    "description": body.get("description", ""),
                    "link_metrics": body.get("link_metrics", {}),
                }
                for name, body in network["scenarios"].items()
            },
        },
        "traces": traces,
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"wrote {OUT_PATH}  ({size_kb:.1f} KB, {len(traces)} traces)")


if __name__ == "__main__":
    main()