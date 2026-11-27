"""会话服务：新建会话、消息落库、读取会话数据

职责边界：这里只管数据读写，不掺 HTTP 语义（404 / 422 由 router 负责），
也不做消息格式转换。把数据转成 langchain 消息并组装上下文在 app.context.history。

对话历史数据入口：load_messages 返回 ORM 行，给接口序列化、前端渲染，
也给 app.context.history 组装成模型可用的消息。
"""

from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatMessage, ChatSession, ChatSummary, ChatToolCall, ChatTurn

# 会话接口分页默认上限；上下文组装不再按固定条数截断
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
    platform: str = "",
    model: str = "",
) -> ChatMessage | None:
    """往会话追加一条消息及其工具调用，并同步维护计数 / 标题 / 活跃时间。

    工具调用与消息在同一事务落库；会话不存在或不属于该用户返回 None。
    user 消息落库时创建 chat_turn 行（除非调用方已指定 turn_id），
    后续 assistant / 工具行由调用方传入同一个 turn_id。
    """
    session = await get_session(db, session_id, user_id)
    if session is None:
        return None

    # user 消息开一轮：创建 chat_turn 行，turn_id 取自它的自增 id
    if role == "user" and turn_id is None:
        turn = ChatTurn(session_id=session.id, platform=platform, model=model)
        db.add(turn)
        await db.flush()  # 拿到 turn.id
        turn_id = turn.id

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
    limit: int | None = None,
    before_id: int | None = None,
) -> Sequence[ChatMessage]:
    """取会话消息，按时间正序返回；默认 limit=None，不截断。

    before_id 用于前端上滚翻页：只取 id 小于它的消息。
    已摘要消息（is_summary=true）仍返回——用户翻历史能看到原文；
    对话上下文由 app.context.history 过滤，不在这里处理。
    """
    conds = [ChatMessage.session_id == session_id]
    if before_id is not None:
        conds.append(ChatMessage.id < before_id)

    query = select(ChatMessage).where(*conds).order_by(ChatMessage.id.desc())
    if limit is not None:
        query = query.limit(max(1, limit))
    rows = await db.scalars(query)
    return list(reversed(rows.all()))  # 取最新 N 条后转回时间正序


async def load_unsummarized_messages(
    db: AsyncSession, session_id: int
) -> Sequence[ChatMessage]:
    """读取会话中尚未被摘要覆盖的全部消息（按 id 正序），供历史压缩使用。

    在 SQL 层过滤 is_summary=true，避免把已摘要消息捞出来再在 Python 里丢弃；
    不设 limit，保证 limit 窗口外的旧轮次也能参与摘要。
    """
    rows = await db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.is_summary.is_(False),
        )
        .order_by(ChatMessage.id)
    )
    return list(rows.all())


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


async def load_turn_usages(db: AsyncSession, turn_ids: list[int]) -> dict[int, ChatTurn]:
    """按 id 批量取 turn，供消息接口把 usage 挂到对应助手消息上。"""
    if not turn_ids:
        return {}
    rows = await db.scalars(select(ChatTurn).where(ChatTurn.id.in_(turn_ids)))
    return {t.id: t for t in rows.all()}


async def record_turn_usage(
    db: AsyncSession,
    turn_id: int | None,
    *,
    usage_events: list[dict],
    platform: str = "",
    model: str = "",
) -> None:
    """把一轮里多次模型调用的 usage 汇总写到 chat_turns。

    usage_events 是 ChatManager 产出的 usage 事件列表（每段一次调用）。
    累加值用于计费口径；last_* 取最后一段，表示本轮结束时的上下文快照。
    """
    if turn_id is None or not usage_events:
        return
    turn = await db.get(ChatTurn, turn_id)
    if turn is None:
        return

    valid = [e for e in usage_events if isinstance(e.get("input_tokens"), int)]
    if not valid:
        return
    total_input = sum(e["input_tokens"] for e in valid)
    total_output = sum(e.get("output_tokens") or 0 for e in valid)
    last = valid[-1]

    turn.input_tokens = total_input
    turn.output_tokens = total_output
    turn.total_tokens = sum(e.get("total_tokens") or 0 for e in valid)
    turn.last_input_tokens = last["input_tokens"]
    turn.last_output_tokens = last.get("output_tokens") or 0
    turn.model_calls = len(valid)
    if platform:
        turn.platform = platform
    if model:
        turn.model = model
    # details 取最后一段的（反映最终状态；累加没有意义）
    if "input_token_details" in last:
        turn.input_token_details = last["input_token_details"]
    if "output_token_details" in last:
        turn.output_token_details = last["output_token_details"]

    await db.commit()


async def load_latest_usage_turn(
    db: AsyncSession, session_id: int
) -> ChatTurn | None:
    """取最近一轮带真实上下文快照的 turn；纯数据读取，用量计算在 app.context.usage。"""
    return await db.scalar(
        select(ChatTurn)
        .where(ChatTurn.session_id == session_id, ChatTurn.last_input_tokens > 0)
        .order_by(ChatTurn.id.desc())
        .limit(1)
    )


async def invalidate_usage_snapshots(db: AsyncSession, session_id: int) -> int:
    """清掉该会话所有轮的 API 上下文快照，让用量回退到估算。

    压缩后历史口径变了，旧 turn 的 last_* 已不代表当前上下文；
    只清 last_*，保留 input/output/total 的计费累加值。
    """
    turns = (
        await db.scalars(
            select(ChatTurn).where(
                ChatTurn.session_id == session_id,
                ChatTurn.last_input_tokens > 0,
            )
        )
    ).all()
    for turn in turns:
        turn.last_input_tokens = 0
        turn.last_output_tokens = 0
    return len(turns)


async def get_summary(db: AsyncSession, session_id: int) -> ChatSummary | None:
    """取会话摘要；一个会话最多一条。"""
    return await db.scalar(
        select(ChatSummary).where(ChatSummary.session_id == session_id)
    )


async def mark_summarized(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    *,
    message_ids: set[int],
    summary: str,
    model: str = "",
) -> int:
    """把已被摘要覆盖的原始消息打 is_summary 标记，并 upsert 会话摘要。

    消息原文保留供用户翻看，但 app.context.history 会过滤它们，不再进对话上下文。
    同一事务里完成"打标 + 存摘要"，避免中途失败留下半压缩状态。
    返回打标的消息数，会话不存在返回 -1。
    """
    session = await get_session(db, session_id, user_id)
    if session is None:
        return -1

    rows = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.id.in_(message_ids),
            )
        )
    ).all()
    for row in rows:
        row.is_summary = True

    existing = await get_summary(db, session_id)
    if existing is None:
        db.add(
            ChatSummary(
                session_id=session_id,
                content=summary.strip(),
                model=model,
            )
        )
    else:
        existing.content = summary.strip()
        existing.model = model

    # 历史口径已变：清掉旧 turn 的 API 上下文快照，下次问答写入新快照前一律估算。
    await invalidate_usage_snapshots(db, session_id)

    await db.commit()
    return len(rows)


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



