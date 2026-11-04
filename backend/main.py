"""FastAPI backend for the campus network latency investigation agent.

Serves the static frontend (``docs/``) and exposes four JSON endpoints:

- ``GET  /api/health``     service + model configuration
- ``GET  /api/cases``      the five test cases from ``tests/cases.json``
- ``GET  /api/network``    topology + per-link metrics for one scenario
- ``POST /api/investigate`` run the agent (DeepSeek) or the offline rule fallback

Run locally:

    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from backend.llm_bridge import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    run_investigation_deepseek,
)
from backend.mock_engine import build_mock_result  # noqa: E402
from src.tools import set_active_scenario  # noqa: E402

DOCS_DIR = BASE_DIR / "docs"
DATA_PATH = BASE_DIR / "data" / "sample_data.json"
CASES_PATH = BASE_DIR / "tests" / "cases.json"

app = FastAPI(
    title="Campus NOC Copilot API",
    description="校园网延迟调查 Agent 的 Web 后端：复用 CLI 的同一套 Agent 与 4 个工具。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenarios() -> dict[str, Any]:
    return _read_json(DATA_PATH).get("scenarios", {})


def _deepseek_key(override: str | None) -> str:
    return (override or os.getenv("DEEPSEEK_API_KEY", "")).strip()


def _model_name() -> str:
    return os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _model_base_url() -> str:
    return os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


class InvestigateRequest(BaseModel):
    prompt: str = Field(min_length=4, description="工程师对故障的自然语言描述")
    scenario: str = Field(default="congestion", description="模拟的当前网络状态")
    use_skill: bool = Field(default=True, description="是否注入 Skill（C 组 / B 组开关）")
    max_tool_rounds: int = Field(default=5, ge=1, le=8)
    api_key: str | None = Field(default=None, description="页面内临时填写的 DeepSeek Key")


class InvestigateResponse(BaseModel):
    output: str
    trace: list[dict[str, Any]]
    stats: dict[str, Any]
    scenario: str
    model: str
    source: str
    warning: str | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "campus-noc-copilot",
        "version": app.version,
        "model": _model_name(),
        "base_url": _model_base_url(),
        "has_api_key": bool(_deepseek_key(None)),
        "scenarios": list(_scenarios().keys()),
    }


@app.get("/api/cases")
def cases() -> dict[str, Any]:
    return _read_json(CASES_PATH)


@app.get("/api/network")
def network(scenario: str = "congestion") -> dict[str, Any]:
    data = _read_json(DATA_PATH)
    scenarios = data.get("scenarios", {})
    if scenario not in scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"未知场景 '{scenario}'，可选：{list(scenarios.keys())}",
        )
    return {
        "topology": data["topology"],
        "scenario": scenario,
        "description": scenarios[scenario].get("description", ""),
        "metrics": scenarios[scenario]["link_metrics"],
        "scenarios": list(scenarios.keys()),
    }


@app.post("/api/investigate", response_model=InvestigateResponse)
def investigate(payload: InvestigateRequest) -> InvestigateResponse:
    if payload.scenario not in _scenarios():
        raise HTTPException(
            status_code=400,
            detail=f"未知场景 '{payload.scenario}'，可选：{list(_scenarios().keys())}",
        )

    api_key = _deepseek_key(payload.api_key)
    if not api_key:
        result = build_mock_result(payload.scenario, payload.prompt)
        return InvestigateResponse(
            **result,
            warning="未配置 DEEPSEEK_API_KEY，本次为离线规则判读（非大模型输出）。",
        )

    try:
        result = run_investigation_deepseek(
            prompt=payload.prompt,
            api_key=api_key,
            scenario=payload.scenario,
            use_skill=payload.use_skill,
            max_tool_rounds=payload.max_tool_rounds,
            model=_model_name(),
            base_url=_model_base_url(),
        )
        return InvestigateResponse(**result)
    except Exception as exc:  # noqa: BLE001 - degrade instead of returning a blank page
        result = build_mock_result(payload.scenario, payload.prompt)
        return InvestigateResponse(
            **result,
            warning=f"DeepSeek 调用失败，已回退到离线规则判读：{exc}",
        )


# The static site is mounted at "/" *after* the API routes, so API paths keep
# priority. Using docs/ as the site root means the exact same files work on
# GitHub Pages (Settings -> Pages -> /docs) without any path rewriting.
if DOCS_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DOCS_DIR), html=True), name="site")


def _self_check() -> None:
    """Small smoke check: python -m backend.main"""
    set_active_scenario("congestion")
    print(json.dumps(health(), ensure_ascii=False, indent=2))
    print(json.dumps(build_mock_result("congestion", "自检")["stats"], ensure_ascii=False))


if __name__ == "__main__":
    _self_check()