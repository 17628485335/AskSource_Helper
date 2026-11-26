"""Chat 路由：SSE 流式问答

事件顺序：meta → (segment_start → token*/reasoning*/tool_start*/tool_end*/citations*)* → done；异常时产出 error 后结束。
（事件语义与 astream_events 的映射表见 app/graph/stream_protocol.py；citations 是工具返回的结构化引用，
一次工具调用可能多帧，前端按 index 去重累加。）
上游静默超过 KEEPALIVE_IDLE 会插入 `: keepalive` 注释帧（客户端按规范忽略），
用于撑住反向代理的空闲超时——推理模型首字可能等上一分钟以上。
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from auth.deps import get_current_user
from auth.schemas import UserOut

from .schemas import ChatRequest
from .service import stream_chat

router = APIRouter(tags=["chat"])

KEEPALIVE_IDLE = 15.0

# 队列里的特殊载荷
_END = object()


def _sse(event: dict) -> str:
    """编码为 SSE 帧：事件名与 data 内的 type 一致，前端两种写法都能监听"""
    return (
        f"event: {event.get('type', 'message')}\n"
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    )


async def _with_keepalive(frames: AsyncIterator[str], idle: float = KEEPALIVE_IDLE) -> AsyncIterator[str]:
    """给帧流加心跳，并在消费端关闭（客户端断开）时取消上游流。

    不做心跳的话，首字之前的漫长静默会被 nginx 一类代理按 proxy_read_timeout
    （默认 60s）判定为死连接而掐断，表现为「大模型聊到一半突然断」。
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for frame in frames:
                await queue.put(frame)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # 原样交给消费侧抛出，避免异常无人接收
            await queue.put(("error", exc))
            return
        await queue.put(_END)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=idle)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _END:
                break
            if isinstance(item, tuple) and item[0] == "error":
                raise item[1]
            yield item
    finally:
        if not task.done():
            task.cancel()  # 让上游的模型流一起结束，别继续烧 token
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _event_stream(payload: ChatRequest, user_id: int) -> AsyncIterator[str]:
    """把 service 编排出的事件流编成 SSE 帧（会话/落库/调模型都不在这里）"""
    events = stream_chat(
        user_id=user_id,
        message=payload.message,
        session_id=payload.session_id,
        platform=payload.platform,
        model=payload.model,
        thinking=payload.thinking,
        workspace_id=payload.workspace_id,
        regenerate=payload.regenerate,
        agent_key=payload.agent_key,
    )
    async for event in events:
        yield _sse(event)


@router.post("/chat", summary="SSE 流式问答")
async def chat(
    payload: ChatRequest,
    current_user: UserOut = Depends(get_current_user),
) -> StreamingResponse:
    """text/event-stream 逐字返回"""
    return StreamingResponse(
        _with_keepalive(_event_stream(payload, current_user.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭反向代理缓冲，否则会被攒成一次性响应
        },
    )
