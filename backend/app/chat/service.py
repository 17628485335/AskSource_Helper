"""Chat 服务层：把一次流式问答编排成事件流

分层边界：
- ChatManager 是模型池（启动预热、管理员保存后重建），ModelAgent 只管模型态和「问模型」：
  本模块用 pick() 挑现成实例（一个模型一份图），调 stream() 产出 token/reasoning/tool_start/tool_end/citations
  （事件定义在 app/graph/stream_protocol.py），请求路径上不建任何东西。
- 深度思考是逐轮参数：先经 agent.effective_thinking() 把「该行不支持」和「没表态」归一成
  具体布尔值，再用同一个值落库、写 meta、传给 stream()，保证三者不会说不一致。
- 本模块管模型之外的一切：解析并落库用户消息、会话与工作区归属、取历史、落库回复，
  并补上 meta / done / error 事件。router 只负责把这里的事件编码成 SSE。
- 助手回复的落库放在 finally：客户端中途断开（router 的 keepalive 会 cancel 上游）或
  上游报错时，已经生成的那一段也要入库。只在全新遍历结束时写会留下只有 user、没有
  assistant 的悬空一轮，下一轮历史就是两条连着的 user。
- 思考增量（reasoning 事件）只转发不落库：buffer 只累加 token，重新进会话看不到思考过程，
  但下一轮历史也不会把几十上百字的推理当成回答送回去。
- 引用（citations 事件）同理只转发不落库：卡片是本轮流式的产物，重进历史会话不展示；
  但模型写在正文里的 [n] 与链接会随回答文本入库，历史消息仍看得见它引用了什么。
- 数据库分三段各开短会话：一次流式回答可能挂数十秒，全程持有请求级会话会长时间占用
  连接池连接，并发稍高就耗尽。（实测 FastAPI 注入的 db 在流式期间仍存活，
  所以这是资源占用问题，不是 correctness 问题。）
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from app.session import service as session_service
from app.workspace import service as workspace_service

from .chat_manager import ChatConfigError, ChatManager


async def stream_chat(
    *,
    user_id: int,
    message: str,
    session_id: int | None = None,
    platform: str = "",
    model: str = "",
    thinking: bool | None = None,
    system_prompt: str | None = None,
    workspace_id: int | None = None,
    regenerate: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """执行一次流式问答，逐个产出事件字典。

    事件：meta（会话与模型信息）→ token*（正文增量）→ reasoning*（思考增量，仅深度档）
    → tool_start*/tool_end*（工具生命周期）→ citations*（工具返回的引用）→ done；
    任何阶段失败都产出 error 事件并结束，避免前端干等到超时。事件语义见 graph/stream_protocol.py。

    system_prompt 逐轮生效，不传则用该 ModelAgent 的默认提示词。
    thinking 只有在该模型支持深度思考时才生效（不支持时按快速发）。
    """
    from auth.database import AsyncSessionLocal

    # 阶段一：挑模型、准备会话与历史
    async with AsyncSessionLocal() as db:
        try:
            pool = await ChatManager.get(db)
            agent = pool.pick(platform=platform, model=model)
            use_thinking = agent.effective_thinking(thinking)
        except ChatConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        except Exception as exc:  # 读库失败 / 模型构建失败
            yield {
                "type": "error",
                "message": f"模型初始化失败：{exc.__class__.__name__}: {exc}",
            }
            return

        if session_id:
            existing = await session_service.get_session(db, session_id, user_id)
            if existing is None:
                yield {"type": "error", "message": "会话不存在"}
                return
            sid = session_id
            # 重新生成：先删掉本轮（末条 user 及其后续回答），再走下方追加新提问的正常流程
            if regenerate:
                await session_service.truncate_last_turn(db, sid, user_id)
        else:
            # 新会话才解析工作区归属：校验所有权，未传则回落默认区；
            # 已有会话的归属不随请求参数漂移
            try:
                wid = await workspace_service.resolve_owned_id(db, user_id, workspace_id)
            except workspace_service.WorkspaceError as exc:
                yield {"type": "error", "message": str(exc)}
                return
            created = await session_service.create_session(
                db,
                user_id=user_id,
                platform=agent.platform,
                model=agent.model_name,
                thinking=use_thinking,
                workspace_id=wid,
            )
            sid = created.id

        await session_service.append_message(
            db, sid, user_id, role="user", content=message
        )
        history = await session_service.load_history(db, sid)

    yield {"type": "meta", "session_id": sid, **agent.descriptor(use_thinking)}

    # 阶段二：流式调用模型（不持有数据库连接）
    buffer: list[str] = []
    persisted = False

    async def persist() -> str:
        """把已产出的内容落库（可重入：断开与报错共用），返回落库后的全文。

        断开时只存已经吐出来的字，不标「已中断」也不补占位：前端本来就会把这条
        当成正常回复渲染，多一个后缀只会污染下一轮的上下文。
        """
        nonlocal persisted
        answer = "".join(buffer).strip()
        if answer and not persisted:
            persisted = True
            async with AsyncSessionLocal() as db:
                await session_service.append_message(
                    db, sid, user_id, role="assistant", content=answer
                )
        return answer

    try:
        async for event in agent.stream(
            history, system_prompt=system_prompt, thinking=use_thinking
        ):
            if event["type"] == "token":
                buffer.append(event["text"])
            yield event
    except Exception as exc:  # 网络 / 上游错误转成事件，不让流静默中断
        await persist()
        yield {"type": "error", "message": f"{exc.__class__.__name__}: {exc}"}
        return
    else:
        answer = await persist()
        yield {"type": "done", "session_id": sid, "content": answer}
    finally:
        # 客户端断开：这里会被抛 GeneratorExit / CancelledError。不能再接着 yield，
        # 但仍可以 await —— shield 保证写事务不会被取消掉，拿不到结果也得让它跑完。
        if not persisted:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(persist())
