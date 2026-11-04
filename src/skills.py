"""Agent Skill 加载器。

Skill 是 ``skills/<name>/SKILL.md``：YAML 前置元数据（name、description）+ 正文。
按 Anthropic Agent Skills 的渐进式披露约定，本项目分两层使用：

1. 元数据（name / description）——仅由 ``use_skill=True`` 时随正文一起注入，
   因为本项目只有一个 Skill，不存在"从多个 Skill 中挑选"的场景；
2. 正文（SKILL.md body）——注入 System Prompt，约束调查流程与判断规则。

第三层 ``reference.md`` 不会自动加载：本 Agent 没有文件系统工具。它保留给
维护者查阅，以及将来接入文件读取工具时按需加载。

不依赖 PyYAML，只解析 Skill 需要的标量与折叠块（``>`` / ``|``）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# 本项目使用的 Skill（对应 skills/<name>/SKILL.md）
DEFAULT_SKILL = "network-latency-investigation"

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(.*)\Z", re.S)
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$")


@dataclass(frozen=True)
class Skill:
    """一个已加载的 Skill。"""

    name: str
    description: str
    body: str

    def as_prompt(self) -> str:
        """渲染为注入 System Prompt 的文本块。"""
        return (
            f"## Skill：{self.name}\n"
            f"（说明：{self.description}）\n\n"
            f"{self.body.strip()}\n"
        )


def _parse_frontmatter(raw: str) -> dict[str, str]:
    """解析扁平的 YAML 前置元数据，支持 ``key: value``、``>`` 与 ``|`` 折叠块。"""
    meta: dict[str, str] = {}
    key: str | None = None
    buffer: list[str] = []

    for line in raw.splitlines():
        match = _KEY_RE.match(line)
        if match and not line[:1].isspace():
            if key is not None:
                meta[key] = " ".join(buffer).strip()
            key, value = match.group(1), match.group(2).strip()
            buffer = [] if value in ("", ">", "|") else [value.strip("\"'")]
        elif key is not None:
            buffer.append(line.strip())

    if key is not None:
        meta[key] = " ".join(buffer).strip()

    return {k: v for k, v in meta.items() if v}


def parse_skill(text: str) -> Skill:
    """把 SKILL.md 文本解析为 :class:`Skill`。"""
    match = _FRONTMATTER_RE.match(text.lstrip("\ufeff"))
    if not match:
        raise ValueError("SKILL.md 缺少以 '---' 包裹的 YAML 前置元数据")
    meta = _parse_frontmatter(match.group(1))
    for required in ("name", "description"):
        if not meta.get(required):
            raise ValueError(f"SKILL.md 前置元数据缺少 '{required}'")
    return Skill(name=meta["name"], description=meta["description"], body=match.group(2))


@lru_cache(maxsize=8)
def load_skill(name: str) -> Skill:
    """按目录名加载 Skill，例如 ``load_skill("network-latency-investigation")``。"""
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到 Skill 文件：{path}")
    return parse_skill(path.read_text(encoding="utf-8"))


def load_skill_prompt(name: str) -> str:
    """加载 Skill 并渲染为可直接拼接进 System Prompt 的文本。"""
    return load_skill(name).as_prompt()