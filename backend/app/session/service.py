"""会话服务：新建会话、消息落库、读取对话历史

职责边界：这里只管数据读写，不掺 HTTP 语义（404 / 422 由 router 负责）。
chat / graph 代码可直接调用本模块，前端则通过 router 暴露的接口访问。

对话历史提供两个入口：
- load_messages：返回 ORM 行，给接口序列化、前端渲染；
- load_history：返回 langchain BaseMessage，可直接拼进 create_agent 的 messages。
"""

from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatMessage, ChatSession, ChatToolCall

# 默认只带最近若干轮进 prompt，避免上下文超长
DEFAULT_HISTORY_LIMIT = 20
# 自动标题截取长度
AUTO_TITLE_LEN = 30


async def create_session(
    db: AsyncSession,
    *,
    user_id: int,
    title: str = "",
    platform: str = "",
    model: str = "",
    thinking: bool = False,
    workspace_id: int | None = None,
) -> ChatSession:
    """新建一个会话并落库；标题留空时后续由首条用户消息自动补上"""
    session = ChatSession(
        user_id=user_id,
        title=title.strip(),
        platform=platform,
        model=model,
        thinking=thinking,
        workspace_id=workspace_id,
        status="active",
        message_count=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)  # 取回 created_at 等服务端默认值
    return session


async def get_session(
    db: AsyncSession, session_id: int, user_id: int
) -> ChatSession | None:
    """按 id 取会话，同时校验归属；不属于该用户一律视为不存在"""
    return await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )


async def list_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
    status: str | None = "active",
    keyword: str = "",
    workspace_id: int | None = None,
) -> tuple[list[ChatSession], int]:
    """分页返回某用户的会话（按最近更新排序）及其总数。

    status 传 None 表示不按状态过滤；keyword 对标题做模糊匹配；
    workspace_id 非空时只返回该工作区下的会话。
    """
    conds = [ChatSession.user_id == user_id]
    if status:
        conds.append(ChatSession.status == status)
    if keyword:
        conds.append(ChatSession.title.like(f"%{keyword.strip()}%"))
    if workspace_id:
        conds.append(ChatSession.workspace_id == workspace_id)

    rows = await db.scalars(
        select(ChatSession)
        .where(*conds)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(max(1, limit))
        .offset(max(0, offset))
    )
    total = await db.scalar(select(func.count()).select_from(ChatSession).where(*conds))
    return list(rows.all()), int(total or 0)


async def update_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    *,
    title: str | None = None,
    status: str | None = None,
) -> ChatSession | None:
    """改标题或切换归档状态；找不到（或不属于该用户）返回 None"""
    session = await get_session(db, session_id, user_id)
    if session is None:
        return None
    if title is not None:
        session.title = title.strip()[:255]
    if status is not None:
        session.status = status
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session_id: int, user_id: int) -> bool:
    """删除会话；消息由 FK ON DELETE CASCADE（配合被动删除）一并清理"""
    session = await get_session(db, session_id, user_id)
    if session is None:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def append_message(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    *,
    role: str,
    content: str,
    tool_name: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    turn_id: int | None = None,
    tokens: int = 0,
) -> ChatMessage | None:
    """往会话追加一条消息及其工具调用，并同步维护计数 / 标题 / 活跃时间。

    工具调用与消息在同一事务落库；会话不存在或不属于该用户返回 None。
    """
    session = await get_session(db, session_id, user_id)
    if session is None:
        return None

    text = content.strip()
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=text,
        turn_id=turn_id,
        tool_name=tool_name,
        tokens=tokens,
    )
    db.add(message)
    await db.flush()  # 先拿到 message.id，工具行才能带上外键
    # user 行就是一轮的锚点，turn_id 回填为自己；assistant / 工具行由调用方传入同一个 id
    if role == "user" and turn_id is None:
        message.turn_id = message.id

    for call in tool_calls or []:
        db.add(
            ChatToolCall(
                session_id=session.id,
                message_id=message.id,
                turn_id=turn_id,
                seq=call.get("seq", 0),
                segment_id=call.get("segment_id"),
                tool_name=call.get("tool_name", ""),
                call_id=call.get("call_id", ""),
                input_json=call.get("input") or {},
                result_text=call.get("result") or "",
                preview=call.get("preview") or "",
                duration_ms=call.get("duration_ms"),
                citations_json=call.get("citations") or [],
            )
        )

    # 首条用户消息充当会话标题，省去前端另外起名
    if role == "user" and not session.title:
        session.title = text[:AUTO_TITLE_LEN]
    session.message_count = (session.message_count or 0) + 1
    # 上一行产生了 UPDATE，触发 updated_at 的 onupdate，会话列表按最近对话排序

    await db.commit()
    await db.refresh(message)
    return message


async def load_messages(
    db: AsyncSession,
    session_id: int,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    before_id: int | None = None,
) -> Sequence[ChatMessage]:
    """取会话内最近 limit 条消息，按时间正序返回。

    before_id 用于前端上滚翻页：只取 id 小于它的消息。
    """
    conds = [ChatMessage.session_id == session_id]
    if before_id is not None:
        conds.append(ChatMessage.id < before_id)

    rows = await db.scalars(
        select(ChatMessage)
        .where(*conds)
        .order_by(ChatMessage.id.desc())
        .limit(max(1, limit))
    )
    return list(reversed(rows.all()))  # 取最新 N 条后转回时间正序


async def load_tool_calls(
    db: AsyncSession, message_ids: Sequence[int]
) -> list[ChatToolCall]:
    """按消息 id 批量取工具调用，按本轮 seq 排序，供 /messages 响应附带"""
    if not message_ids:
        return []
    rows = await db.scalars(
        select(ChatToolCall)
        .where(ChatToolCall.message_id.in_(message_ids))
        .order_by(ChatToolCall.seq.asc(), ChatToolCall.id.asc())
    )
    return list(rows.all())


async def count_messages(db: AsyncSession, session_id: int) -> int:
    """统计某会话的消息总数"""
    total = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    return int(total or 0)


async def truncate_last_turn(
    db: AsyncSession, session_id: int, user_id: int
) -> int:
    """删除会话最后一轮：从最后一条 user 消息起（含）到末尾的全部消息。

    用于前端「编辑末条提问后重新生成」：先清掉旧提问及其后续回答，
    再由调用方按正常流程追加新的 user 消息，避免历史里出现重复轮次。
    会话不存在或没有 user 消息返回 0；否则返回删除的行数。
    """
    session = await get_session(db, session_id, user_id)
    if session is None:
        return 0
    last_user_id = await db.scalar(
        select(func.max(ChatMessage.id)).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "user"
        )
    )
    if last_user_id is None:
        return 0
    rows = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.id >= last_user_id,
            )
        )
    ).all()
    for r in rows:
        await db.delete(r)
    session.message_count = max(0, (session.message_count or 0) - len(rows))
    await db.commit()
    return len(rows)


def to_lc_messages(rows: Sequence[ChatMessage]) -> list[Any]:
    """把 ORM 消息行转成 langchain 消息对象（惰性导入，未装 langchain 也不影响本模块导入）

    tools 角色跳过：langchain 的 ToolMessage 必须携带 tool_call_id，
    当前表结构没存，硬塞会让后续请求被上游判为非法上下文。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    mapping = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
    out: list[Any] = []
    for row in rows:
        cls = mapping.get(row.role)
        if cls is None:
            continue
        out.append(cls(content=row.content))
    return out


async def load_history(
    db: AsyncSession,
    session_id: int,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    before_id: int | None = None,
) -> list[Any]:
    """读会话历史并转成 langchain 消息列表，可直接用于 create_agent / model.ainvoke"""
    return to_lc_messages(await load_messages(db, session_id, limit=limit, before_id=before_id))


async def get_recent_session(
    db: AsyncSession, user_id: int, *, status: str = "active"
) -> ChatSession | None:
    """取用户最近活跃的一个会话（前端「继续上次对话」用）"""
    rows = await db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.status == status)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(1)
    )
    return rows.first()
