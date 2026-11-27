"""Agent 定义与提示词版本的数据读写；不负责 HTTP 状态码。"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.prompt import compute_prompt_hash

from .models import Agent, AgentPrompt
from .schemas import AgentCreate, AgentOut, AgentPromptCreate, AgentPromptOut, AgentUpdate


class AgentNotFound(Exception):
    """按 id / key 找不到 agent"""


class AgentKeyExists(Exception):
    """agent_key 重复"""


class PromptNotFound(Exception):
    """指定的提示词版本不存在"""


@dataclass(frozen=True)
class AgentContext:
    """一次请求实际生效的 agent 配置；空字符串表示沿用请求值/代码默认值"""

    agent_id: int
    agent_key: str
    prompt_version: int | None
    system_prompt: str | None
    platform: str
    model: str
    thinking: bool
    tool_names: list[str] | None


def _agent_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        agent_key=agent.agent_key,
        name=agent.name,
        description=agent.description,
        platform=agent.platform,
        model=agent.model,
        thinking=agent.thinking,
        tool_names=agent.tool_names_json,
        active_prompt_version=agent.active_prompt_version,
        is_active=agent.is_active,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _prompt_out(prompt: AgentPrompt) -> AgentPromptOut:
    return AgentPromptOut(
        id=prompt.id,
        agent_id=prompt.agent_id,
        version=prompt.version,
        system_prompt=prompt.system_prompt,
        prompt_hash=prompt.prompt_hash,
        note=prompt.note,
        created_at=prompt.created_at,
    )


async def list_agents(db: AsyncSession, *, active_only: bool = False) -> list[AgentOut]:
    stmt = select(Agent)
    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))
    stmt = stmt.order_by(Agent.id)
    return [_agent_out(row) for row in (await db.scalars(stmt)).all()]


async def get_agent(db: AsyncSession, agent_id: int) -> AgentOut:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")
    return _agent_out(agent)


async def get_agent_by_key(db: AsyncSession, agent_key: str) -> AgentOut:
    agent = (await db.scalars(select(Agent).where(Agent.agent_key == agent_key))).first()
    if agent is None:
        raise AgentNotFound(f"agent_key={agent_key!r} 不存在")
    return _agent_out(agent)


async def create_agent(db: AsyncSession, payload: AgentCreate) -> AgentOut:
    agent = Agent(
        agent_key=payload.agent_key,
        name=payload.name,
        description=payload.description,
        platform=payload.platform,
        model=payload.model,
        thinking=payload.thinking,
        tool_names_json=payload.tool_names,
        active_prompt_version=1 if payload.system_prompt else 0,
        is_active=True,
    )
    db.add(agent)
    try:
        await db.flush()
        if payload.system_prompt:
            db.add(
                AgentPrompt(
                    agent_id=agent.id,
                    version=1,
                    system_prompt=payload.system_prompt,
                    prompt_hash=compute_prompt_hash(payload.system_prompt),
                    note="initial",
                )
            )
            agent.active_prompt_version = 1
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AgentKeyExists(f"agent_key={payload.agent_key!r} 已存在") from exc
    await db.refresh(agent)
    return _agent_out(agent)


async def update_agent(db: AsyncSession, agent_id: int, payload: AgentUpdate) -> AgentOut:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")

    fields = payload.model_dump(exclude_unset=True)
    if "tool_names" in fields:
        fields["tool_names_json"] = fields.pop("tool_names")

    version = fields.get("active_prompt_version")
    if version is not None:
        exists = await db.scalar(
            select(AgentPrompt.id).where(
                AgentPrompt.agent_id == agent_id, AgentPrompt.version == version
            )
        )
        if exists is None:
            raise PromptNotFound(f"agent {agent_id} 没有 v{version} 提示词")

    for key, value in fields.items():
        setattr(agent, key, value)
    await db.commit()
    await db.refresh(agent)
    return _agent_out(agent)


async def delete_agent(db: AsyncSession, agent_id: int) -> None:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")
    await db.delete(agent)
    await db.commit()


async def list_prompts(db: AsyncSession, agent_id: int) -> list[AgentPromptOut]:
    if await db.get(Agent, agent_id) is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")
    rows = (
        await db.scalars(
            select(AgentPrompt)
            .where(AgentPrompt.agent_id == agent_id)
            .order_by(AgentPrompt.version.desc())
        )
    ).all()
    return [_prompt_out(row) for row in rows]


async def create_prompt(
    db: AsyncSession, agent_id: int, payload: AgentPromptCreate
) -> AgentPromptOut:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")

    max_version = await db.scalar(
        select(func.coalesce(func.max(AgentPrompt.version), 0)).where(
            AgentPrompt.agent_id == agent_id
        )
    )
    prompt = AgentPrompt(
        agent_id=agent_id,
        version=int(max_version or 0) + 1,
        system_prompt=payload.system_prompt,
        prompt_hash=compute_prompt_hash(payload.system_prompt),
        note=payload.note,
    )
    db.add(prompt)
    if payload.activate:
        agent.active_prompt_version = prompt.version
    await db.commit()
    await db.refresh(prompt)
    return _prompt_out(prompt)


async def activate_prompt(db: AsyncSession, agent_id: int, version: int) -> AgentOut:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"agent {agent_id} 不存在")
    exists = await db.scalar(
        select(AgentPrompt.id).where(
            AgentPrompt.agent_id == agent_id, AgentPrompt.version == version
        )
    )
    if exists is None:
        raise PromptNotFound(f"agent {agent_id} 没有 v{version} 提示词")
    agent.active_prompt_version = version
    await db.commit()
    await db.refresh(agent)
    return _agent_out(agent)


async def resolve_agent(db: AsyncSession, agent_key: str) -> AgentContext:
    """解析本轮生效配置；agent 不存在/停用/无 prompt 时返回空 hint，由调用方兜底。"""
    agent = (
        await db.scalars(
            select(Agent).where(Agent.agent_key == agent_key, Agent.is_active.is_(True))
        )
    ).first()
    if agent is None:
        raise AgentNotFound(f"agent_key={agent_key!r} 不存在或未启用")

    prompt = (
        await db.scalars(
            select(AgentPrompt).where(
                AgentPrompt.agent_id == agent.id,
                AgentPrompt.version == agent.active_prompt_version,
            )
        )
    ).first()

    return AgentContext(
        agent_id=agent.id,
        agent_key=agent.agent_key,
        prompt_version=prompt.version if prompt else None,
        system_prompt=prompt.system_prompt if prompt else None,
        platform=agent.platform,
        model=agent.model,
        thinking=agent.thinking,
        tool_names=agent.tool_names_json,
    )
