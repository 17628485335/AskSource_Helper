"""会话相关路由（均需登录，且只能访问自己的会话）

- POST   /sessions                    新建会话
- GET    /sessions                    分页查询我的会话列表
- GET    /sessions/{id}               会话详情
- PATCH  /sessions/{id}               改名 / 归档
- DELETE /sessions/{id}               删除会话（消息级联删除）
- POST   /sessions/{id}/messages      追加一条消息（对话落库）
- GET    /sessions/{id}/messages      完整历史（含 id/tokens，支持上滚翻页）
- GET    /sessions/{id}/history       精简历史（role/content，拼 prompt 用）

跨用户访问统一返回 404，不暴露会话是否存在。
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_user
from auth.models import User

from app.context import usage as context_usage
from app.workspace import service as workspace_service

from . import mapper
from . import service
from .schemas import (
    ContextUsageOut,
    HistoryMessage,
    MessageCreate,
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionPage,
    SessionUpdate,
)

# 路径已含 /sessions 前缀，此处不再设 prefix，否则会拼成 /sessions/sessions
router = APIRouter(tags=["session"])


async def _owned_session(db: AsyncSession, session_id: int, user_id: int):
    """取归属当前用户的会话，否则 404"""
    session = await service.get_session(db, session_id, user_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建会话",
)
async def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    # 归属校验：指定了工作区就必须是自己的，否则 404（不暴露是否存在）
    if payload.workspace_id is not None:
        ws = await workspace_service.get_owned(db, payload.workspace_id, current_user.id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工作区不存在")
    session = await service.create_session(
        db,
        user_id=current_user.id,
        title=payload.title,
        platform=payload.platform,
        model=payload.model,
        thinking=payload.thinking,
        workspace_id=payload.workspace_id,
    )
    return SessionOut.model_validate(session)


@router.get(
    "/sessions",
    response_model=SessionPage,
    summary="查询我的会话列表",
)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    status_filter: Literal["active", "archived", "all"] = Query(
        default="active", alias="status", description="按状态过滤，all 表示不过滤"
    ),
    keyword: str = Query(default="", max_length=64, description="按标题模糊搜索"),
    workspace_id: int | None = Query(default=None, ge=1, description="只看某工作区下的会话"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionPage:
    rows, total = await service.list_sessions(
        db,
        current_user.id,
        limit=limit,
        offset=offset,
        status=None if status_filter == "all" else status_filter,
        keyword=keyword,
        workspace_id=workspace_id,
    )
    return SessionPage(
        items=[SessionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="会话详情",
)
async def read_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    session = await _owned_session(db, session_id, current_user.id)
    return SessionOut.model_validate(session)


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionOut,
    summary="修改会话标题 / 状态",
)
async def modify_session(
    session_id: int,
    payload: SessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    if payload.title is None and payload.status is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="至少提供 title 或 status"
        )
    session = await service.update_session(
        db, session_id, current_user.id, title=payload.title, status=payload.status
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return SessionOut.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话",
)
async def remove_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await service.delete_session(db, session_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="追加一条消息",
)
async def add_message(
    session_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """写入一条消息；会话标题为空且 role=user 时自动取首行内容作标题。"""
    message = await service.append_message(
        db,
        session_id,
        current_user.id,
        role=payload.role,
        content=payload.content,
        tool_name=payload.tool_name,
        tokens=payload.tokens,
    )
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return MessageOut.model_validate(message)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageOut],
    summary="查询会话消息（完整字段）",
)
async def read_messages(
    session_id: int,
    limit: int = Query(default=service.DEFAULT_HISTORY_LIMIT, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1, description="只取该 id 之前的消息，用于上滚翻页"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    await _owned_session(db, session_id, current_user.id)
    rows = await service.load_messages(db, session_id, limit=limit, before_id=before_id)
    tool_rows = await service.load_tool_calls(db, [r.id for r in rows])
    turns = await service.load_turn_usages(db, [r.turn_id for r in rows if r.turn_id])
    return mapper.to_message_outs(list(rows), tool_rows, turns)


@router.get(
    "/sessions/{session_id}/context-usage",
    response_model=ContextUsageOut,
    summary="查询会话上下文用量",
)
async def context_usage(
    session_id: int,
    context_size: int = Query(default=200000, ge=1, description="当前模型的上下文窗口 tokens"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextUsageOut:
    """只算未摘要消息 + 摘要：与实际送进模型的上下文口径一致。"""
    await _owned_session(db, session_id, current_user.id)
    return ContextUsageOut(**await context_usage.get_context_usage(db, session_id, context_size=context_size))


@router.get(
    "/sessions/{session_id}/history",
    response_model=list[HistoryMessage],
    summary="查询对话历史（精简视图）",
)
async def read_history(
    session_id: int,
    limit: int = Query(default=service.DEFAULT_HISTORY_LIMIT, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HistoryMessage]:
    """按时间正序返回 role/content 精简视图；送进模型的上下文由 app.context.history 组装。"""
    await _owned_session(db, session_id, current_user.id)
    rows = await service.load_messages(db, session_id, limit=limit)
    return [
        HistoryMessage(
            role=r.role,
            content=r.content,
            tool_name=r.tool_name,
            turn_id=r.turn_id,
        )
        for r in rows
    ]
