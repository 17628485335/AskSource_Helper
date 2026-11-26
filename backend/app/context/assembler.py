"""把 agent 绑定、agent 文档、用户文档和生成内容装配成上下文消息。

Phase 4 还没有精确 token 计数（Phase 0），这里用字符数 / 4 做保守估算。
正式接入 tiktoken 后只需替换 estimate_tokens，整体装配逻辑不用变。
"""

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import SystemMessage

from app.agents.service import AgentContext
from app.graph import list_tool_specs
from app.prompt import section_header

from . import service as context_service
import app.tools  # noqa: F401  确保工具注册到 registry，Skills Snapshot 才拿得到内容

DEFAULT_MAX_CONTEXT_TOKENS = 8000
TRUNCATE_MARK = "\n…（内容已按预算截断）"


@dataclass(frozen=True)
class ContextBundle:
    """一次请求的上下文装配结果"""

    messages: list[Any]
    section_keys: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    approx_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """Phase 4 的临时估算：中文按 1 字≈1 token，英文按 4 字符≈1 token 折中。"""
    if not text:
        return 0
    return max(1, len(text) // 2)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """按预算截断；保留可读边界，不硬切在半句话正中间。"""
    tokens = estimate_tokens(text)
    if tokens <= max_tokens:
        return text
    approx_chars = max(16, max_tokens * 2 - len(TRUNCATE_MARK))
    head = text[:approx_chars]
    cut = max(head.rfind("。"), head.rfind("\n"), head.rfind(". "))
    if cut > approx_chars // 2:
        head = head[: cut + 1]
    return head.rstrip() + TRUNCATE_MARK


def build_skills_snapshot(tool_names: list[str] | None) -> str:
    """从工具注册表生成能力快照；不落库正文，避免与真实工具状态漂移。"""
    if tool_names is not None and not tool_names:
        return "本 Agent 未启用任何工具。"

    specs = list_tool_specs()
    if tool_names is not None:
        wanted = set(tool_names)
        specs = [spec for spec in specs if spec.name in wanted]
    else:
        specs = [spec for spec in specs if spec.auto_mount]

    if not specs:
        return "当前没有可用工具。"

    lines = ["可用工具："]
    for spec in specs:
        label = spec.label or spec.name
        suffix = f"，单轮最多 {spec.max_calls} 次" if spec.max_calls > 0 else ""
        lines.append(f"- {spec.name}（{label}）：{spec.description}{suffix}")
    return "\n".join(lines)


def _section_header(key: str, title: str, trust_level: str, hint: str = "") -> str:
    return section_header(key, trust_level, hint) + "\n"


def _section_footer(key: str) -> str:
    return f"\n[/{key}]"


async def build_context(
    db,
    agent_ctx: AgentContext,
    *,
    user_id: int,
    session_id: int | None = None,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> ContextBundle:
    """按 agent 绑定装配上下文。

    - agent 只决定“要什么、顺序、预算、信任级别”
    - 内容按 resolver 从 agent doc / user doc / 生成器读取
    - Phase 5 的 memory resolver 目前跳过，不伪造内容
    """
    bindings = sorted(
        await context_service.list_bindings(db, agent_ctx.agent_id),
        key=lambda item: (item.priority, item.id),
    )
    blocks: list[str] = []
    section_keys: list[str] = []
    skipped: list[dict[str, str]] = []
    used_tokens = 0

    for binding in bindings:
        if not binding.enabled:
            skipped.append({"key": binding.key, "reason": "disabled"})
            continue

        raw = ""
        title = binding.title
        if binding.resolver == "agent_doc":
            doc = await context_service.find_agent_doc(db, agent_ctx.agent_id, binding.ref_key)
            if doc is None or not doc.content.strip():
                skipped.append({"key": binding.key, "reason": "missing_agent_doc"})
                continue
            raw = doc.content
            title = title or doc.title

        elif binding.resolver == "user_doc":
            doc = await context_service.find_user_doc(db, user_id, binding.ref_key)
            if doc is None or not doc.content.strip():
                skipped.append({"key": binding.key, "reason": "missing_user_doc"})
                continue
            raw = doc.content
            title = title or doc.title

        elif binding.resolver == "generated":
            if binding.ref_key != "skills_snapshot":
                skipped.append({"key": binding.key, "reason": "unknown_generator"})
                continue
            raw = build_skills_snapshot(agent_ctx.tool_names)
            if not raw.strip():
                skipped.append({"key": binding.key, "reason": "empty_generated"})

        elif binding.resolver == "memory":
            # Phase 5 才实现 agent_memories；这里只保留绑定的位置，不伪造内容
            skipped.append({"key": binding.key, "reason": "memory_not_implemented"})
            continue

        else:
            skipped.append({"key": binding.key, "reason": "no_resolver"})
            continue

        section = (
            _section_header(binding.key, title, binding.trust_level, getattr(binding, "trust_hint", ""))
            + truncate_to_tokens(raw, binding.max_tokens)
            + _section_footer(binding.key)
        )
        section_tokens = estimate_tokens(section)
        if used_tokens + section_tokens > max_context_tokens:
            skipped.append({"key": binding.key, "reason": "context_budget_exceeded"})
            continue

        blocks.append(section)
        section_keys.append(binding.key)
        used_tokens += section_tokens

    if not blocks:
        return ContextBundle(messages=[], skipped=skipped, approx_tokens=0)

    block = "\n\n".join(blocks)
    return ContextBundle(
        messages=[SystemMessage(content=block)],
        section_keys=section_keys,
        skipped=skipped,
        approx_tokens=used_tokens,
    )
