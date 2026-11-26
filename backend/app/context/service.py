"""上下文段的数据读写；不负责 HTTP 状态码，也不负责拼 prompt。"""

import hashlib

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentContextBinding, AgentContextDoc, AgentMemory, UserContextDoc
from .schemas import (
    AgentContextBindingCreate,
    AgentContextBindingUpdate,
    AgentContextDocCreate,
    AgentContextDocUpdate,
    UserContextDocCreate,
    UserContextDocUpdate,
    AgentMemoryCreate,
    AgentMemoryUpdate,
)


class ContextConflict(Exception):
    """同一 owner 下 key 重复"""


class ContextNotFound(Exception):
    """指定的上下文段 / 文档不存在"""


def content_hash(content: str) -> str:
    """内容 hash：给缓存失效与审计用"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _touch_hash(target: AgentContextDoc | UserContextDoc, content: str) -> None:
    target.content = content
    target.version_hash = content_hash(content)


# ---------------- Agent context bindings ----------------

async def list_bindings(db: AsyncSession, agent_id: int) -> list[AgentContextBinding]:
    return list(
        (
            await db.scalars(
                select(AgentContextBinding)
                .where(AgentContextBinding.agent_id == agent_id)
                .order_by(AgentContextBinding.priority, AgentContextBinding.id)
            )
        ).all()
    )


async def create_binding(
    db: AsyncSession, agent_id: int, payload: AgentContextBindingCreate
) -> AgentContextBinding:
    row = AgentContextBinding(agent_id=agent_id, **payload.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ContextConflict(f"agent {agent_id} 已有上下文段 {payload.key!r}") from exc
    await db.refresh(row)
    return row


async def update_binding(
    db: AsyncSession, binding_id: int, payload: AgentContextBindingUpdate
) -> AgentContextBinding:
    row = await db.get(AgentContextBinding, binding_id)
    if row is None:
        raise ContextNotFound(f"上下文绑定 {binding_id} 不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_binding(db: AsyncSession, binding_id: int) -> None:
    row = await db.get(AgentContextBinding, binding_id)
    if row is None:
        raise ContextNotFound(f"上下文绑定 {binding_id} 不存在")
    await db.delete(row)
    await db.commit()


# ---------------- Agent context docs ----------------

async def list_agent_docs(
    db: AsyncSession, agent_id: int | None = None, *, include_global: bool = True
) -> list[AgentContextDoc]:
    stmt = select(AgentContextDoc)
    if agent_id is not None:
        conds = [AgentContextDoc.agent_id == agent_id]
        if include_global:
            # 专属文档和全局文档都要，两者是 OR；用 where(*conds) 会变成 AND，永远为空
            stmt = stmt.where(or_(conds[0], AgentContextDoc.agent_id.is_(None)))
        else:
            stmt = stmt.where(conds[0])
    elif not include_global:
        stmt = stmt.where(AgentContextDoc.agent_id.is_not(None))
    return list((await db.scalars(stmt.order_by(AgentContextDoc.id))).all())


async def create_agent_doc(
    db: AsyncSession, payload: AgentContextDocCreate
) -> AgentContextDoc:
    # MySQL 的 UNIQUE(agent_id, key) 对 NULL 不生效：多条全局文档同 key 不会被库拦住，
    # 这里显式查一次，保证同 key 的全局文档只有一个来源。
    if payload.agent_id is None:
        duplicate = await db.scalar(
            select(AgentContextDoc.id).where(
                AgentContextDoc.agent_id.is_(None),
                AgentContextDoc.key == payload.key,
            )
        )
        if duplicate is not None:
            raise ContextConflict(f"已有全局 agent 文档 {payload.key!r}")
    row = AgentContextDoc(
        agent_id=payload.agent_id,
        key=payload.key,
        title=payload.title,
        content="",
    )
    _touch_hash(row, payload.content)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ContextConflict(f"agent={payload.agent_id} 已有文档 {payload.key!r}") from exc
    await db.refresh(row)
    return row


async def update_agent_doc(
    db: AsyncSession, doc_id: int, payload: AgentContextDocUpdate
) -> AgentContextDoc:
    row = await db.get(AgentContextDoc, doc_id)
    if row is None:
        raise ContextNotFound(f"agent 文档 {doc_id} 不存在")
    fields = payload.model_dump(exclude_unset=True)
    if "content" in fields:
        _touch_hash(row, fields.pop("content"))
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_agent_doc(db: AsyncSession, doc_id: int) -> None:
    row = await db.get(AgentContextDoc, doc_id)
    if row is None:
        raise ContextNotFound(f"agent 文档 {doc_id} 不存在")
    await db.delete(row)
    await db.commit()


async def find_agent_doc(
    db: AsyncSession, agent_id: int, key: str
) -> AgentContextDoc | None:
    """优先 agent 专属，其次全局共享"""
    row = await db.scalar(
        select(AgentContextDoc).where(
            AgentContextDoc.agent_id == agent_id, AgentContextDoc.key == key
        )
    )
    if row is not None:
        return row
    return await db.scalar(
        select(AgentContextDoc).where(
            AgentContextDoc.agent_id.is_(None), AgentContextDoc.key == key
        )
    )


# ---------------- User context docs ----------------

async def list_user_docs(db: AsyncSession, user_id: int) -> list[UserContextDoc]:
    return list(
        (
            await db.scalars(
                select(UserContextDoc)
                .where(UserContextDoc.user_id == user_id)
                .order_by(UserContextDoc.id)
            )
        ).all()
    )


async def create_user_doc(
    db: AsyncSession, user_id: int, payload: UserContextDocCreate
) -> UserContextDoc:
    row = UserContextDoc(user_id=user_id, key=payload.key, title=payload.title, content="")
    _touch_hash(row, payload.content)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ContextConflict(f"用户已有上下文文档 {payload.key!r}") from exc
    await db.refresh(row)
    return row


async def update_user_doc(
    db: AsyncSession, user_id: int, doc_id: int, payload: UserContextDocUpdate
) -> UserContextDoc:
    row = await db.get(UserContextDoc, doc_id)
    if row is None or row.user_id != user_id:
        raise ContextNotFound(f"用户文档 {doc_id} 不存在")
    fields = payload.model_dump(exclude_unset=True)
    if "content" in fields:
        _touch_hash(row, fields.pop("content"))
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_user_doc(db: AsyncSession, user_id: int, doc_id: int) -> None:
    row = await db.get(UserContextDoc, doc_id)
    if row is None or row.user_id != user_id:
        raise ContextNotFound(f"用户文档 {doc_id} 不存在")
    await db.delete(row)
    await db.commit()


async def find_user_doc(
    db: AsyncSession, user_id: int, key: str
) -> UserContextDoc | None:
    return await db.scalar(
        select(UserContextDoc).where(
            UserContextDoc.user_id == user_id, UserContextDoc.key == key
        )
    )


# ---------------- Agent memories ----------------

async def list_agent_memories(db: AsyncSession, agent_id: int) -> list[AgentMemory]:
    return list(
        (
            await db.scalars(
                select(AgentMemory)
                .where(AgentMemory.agent_id == agent_id)
                .order_by(AgentMemory.id)
            )
        ).all()
    )


async def create_agent_memory(
    db: AsyncSession, agent_id: int, payload: AgentMemoryCreate
) -> AgentMemory:
    row = AgentMemory(agent_id=agent_id, content=payload.content)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_agent_memory(
    db: AsyncSession, agent_id: int, memory_id: int, payload: AgentMemoryUpdate
) -> AgentMemory:
    row = await db.get(AgentMemory, memory_id)
    if row is None or row.agent_id != agent_id:
        raise ContextNotFound(f"长期记忆 {memory_id} 不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_agent_memory(db: AsyncSession, agent_id: int, memory_id: int) -> None:
    row = await db.get(AgentMemory, memory_id)
    if row is None or row.agent_id != agent_id:
        raise ContextNotFound(f"长期记忆 {memory_id} 不存在")
    await db.delete(row)
    await db.commit()
