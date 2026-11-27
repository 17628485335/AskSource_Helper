"""上下文业务层：按 agent 预设取数、拼系统提示词分段、编排 LLM 生成内容。

router 只负责参数校验、权限与异常转 HTTP；业务编排放在这里。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service as agent_service
from app.chat.chat_manager import ChatManager
from app.graph import list_tool_specs
from app.prompt import build_system_prompt, strip_legacy_default_prompt

from . import service as context_service
from .assembler import build_skills_snapshot
from .generator import generate_context_content


async def generate_section_content(
    db: AsyncSession,
    *,
    agent_id: int | None,
    kind: str,
    current: str = "",
    hint: str = "",
    variant: str = "",
) -> str:
    """解析生效的 agent → 从模型池挑模型 → 调 LLM 生成一段上下文内容。"""
    if agent_id is not None:
        agent = await agent_service.get_agent(db, agent_id)
        platform, model = agent.platform, agent.model
    else:
        ctx = await agent_service.resolve_agent(db, "chat")
        platform, model = ctx.platform, ctx.model

    pool = await ChatManager.get(db)
    model_agent = pool.pick(platform=platform, model=model)
    return await generate_context_content(
        model_agent.chat_model,
        kind,
        current=current,
        hint=hint,
        variant=variant,
    )


async def compose_system_prompt(
    db: AsyncSession,
    *,
    prompt: str,
    agent_id: int | None,
    user_id: int,
) -> str:
    """按 binding 的 resolver 取对应内容，组成 sections 后交给 build_system_prompt。"""
    base = strip_legacy_default_prompt(prompt)
    sections: list[tuple[str, str, str, str]] = []
    if agent_id is not None:
        agent = await agent_service.get_agent(db, agent_id)
        all_tools = [spec.name for spec in list_tool_specs()]
        effective_tools = agent.tool_names if agent.tool_names is not None else all_tools
        memories = await context_service.list_agent_memories(db, agent.id)
        for binding in await context_service.list_bindings(db, agent.id):
            if not binding.enabled:
                continue
            ref_key = binding.ref_key or binding.key
            content = ""
            if binding.resolver == "agent_doc":
                doc = await context_service.find_agent_doc(db, agent.id, ref_key)
                content = doc.content if doc else ""
            elif binding.resolver == "user_doc":
                doc = await context_service.find_user_doc(db, user_id, ref_key)
                content = doc.content if doc else ""
            elif binding.resolver == "generated":
                content = build_skills_snapshot(effective_tools)
            elif binding.resolver == "memory":
                content = "\n".join(
                    memory.content.strip()
                    for memory in memories
                    if memory.enabled and memory.content.strip()
                )
            sections.append((binding.key, binding.trust_level, content, binding.trust_hint))
    return build_system_prompt(base, sections=sections)
