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
- 一轮问答以 user 消息 id 作为 turn_id，串起 user / assistant 消息行；content 是给
  UI 与下一轮 prompt 用的纯正文。每次 segment_start 只递增一个轻量 segment_id，
  用来标记工具调用属于第几轮模型调用，不再额外存一份分段正文。
- 工具调用拆到 chat_tool_calls 表：tool_start / tool_end 收集工具名、完整入参、
  call_id、完整结果、耗时与引用，和 assistant 消息在同一事务落库。这样既能按
  call_id / 工具名查询，也不让大段工具原文把消息行撑大。
- 思考增量（reasoning 事件）只转发不落库：重新进会话看不到思考过程，下一轮历史也不会
  把几十上百字的推理当成回答送回去。
- 引用卡片（citations 事件）只转发给前端展示；但它会附在对应的 tool_call 行上落库，
  模型写在正文里的 [n] 与链接也随回答文本入库，历史消息仍看得见它引用了什么。
- 数据库分三段各开短会话：一次流式回答可能挂数十秒，全程持有请求级会话会长时间占用
  连接池连接，并发稍高就耗尽。（实测 FastAPI 注入的 db 在流式期间仍存活，
  所以这是资源占用问题，不是 correctness 问题。）
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from app.agents import service as agent_service
from app.context.history import load_history
from app.session import service as session_service
from app.workspace import service as workspace_service

from .chat_manager import ChatConfigError, ChatManager


async def astream_chat(
    *,
    user_id: int,
    message: str,
    session_id: int | None = None,
    platform: str = "",
    model: str = "",
    thinking: bool | None = None,
    workspace_id: int | None = None,
    regenerate: bool = False,
    agent_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """执行一次流式问答，逐个产出事件字典。

    事件：meta（会话与模型信息）→ (segment_start（分段边界）→ token*（正文增量）
    → reasoning*（思考增量，仅深度档）→ tool_start*/tool_end*（工具生命周期）
    → citations*（工具返回的引用）)* → done；任何阶段失败都产出 error 事件并结束，
    避免前端干等到超时。事件语义见 graph/stream_protocol.py。

    agent_key 命中 agents 表时，表里的提示词/模型/工具白名单优先于请求值；
    提示词统一取 agent_prompts 的生效版本。
    thinking 只有在该模型支持深度思考时才生效（不支持时按快速发）。
    """
    from auth.database import AsyncSessionLocal

    ctx: agent_service.AgentContext | None = None
    tool_names: list[str] | None = None
    agent_prompt: str | None = None

    # 阶段一：解析 agent 配置、挑模型、准备会话与历史
    async with AsyncSessionLocal() as db:
        try:
            # 不传 agent_key 时查默认 chat；没建表/没配记录就继续走代码默认值，
            # 避免一次配置缺失把整个对话打挂。显式指定却不存在的 agent 则直接报错。
            try:
                ctx = await agent_service.resolve_agent(db, agent_key or "chat")
            except agent_service.AgentNotFound:
                if agent_key:
                    yield {"type": "error", "message": f"agent {agent_key!r} 不存在或未启用"}
                    return
            except Exception:
                ctx = None

            pool = await ChatManager.get(db)
            if ctx is not None:
                platform = ctx.platform or platform
                model = ctx.model or model
                if thinking is None:
                    thinking = ctx.thinking
                agent_prompt = ctx.system_prompt
                tool_names = ctx.tool_names

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

        user_message = await session_service.append_message(
            db,
            sid,
            user_id,
            role="user",
            content=message,
            platform=agent.platform,
            model=agent.model_name,
        )
        # append_message 已为这条 user 消息创建 chat_turn 行；assistant / 工具行回指同一个 turn_id。
        turn_id = getattr(user_message, "turn_id", None) if user_message is not None else None
        history = await load_history(db, sid)

    meta_extras: dict[str, Any] = {}
    if ctx is not None:
        meta_extras = {
            "agent_key": ctx.agent_key,
            "prompt_version": ctx.prompt_version,
        }
    yield {"type": "meta", "session_id": sid, **agent.descriptor(use_thinking), **meta_extras}

    # 阶段二：流式调用模型（不持有数据库连接）
    answer_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage_events: list[dict[str, Any]] = []
    seq_counter = 0
    pending_tools: dict[str, dict[str, Any]] = {}
    persisted = False

    def _next_seq() -> int:
        nonlocal seq_counter
        seq_counter += 1
        return seq_counter

    def _tool_key(tool: str, call_id: str) -> str:
        # 个别上游不返回 call_id，退化到按工具名配对（与前端协议一致）
        return call_id or tool

    def _new_tool_call(tool: str, call_id: str) -> dict[str, Any]:
        return {
            "seq": _next_seq(),
            "tool_name": tool,
            "call_id": call_id,
            "input": {},
            "result": "",
            "preview": "",
            "duration_ms": None,
            "citations": [],
        }

    def _find_tool_call(key: str) -> dict[str, Any] | None:
        call = pending_tools.get(key)
        if call is not None:
            return call
        return next(
            (
                c
                for c in reversed(tool_calls)
                if _tool_key(c.get("tool_name", ""), c.get("call_id", "")) == key
            ),
            None,
        )

    async def persist() -> str:
        """把已产出的正文与工具调用落库（可重入：断开与报错共用）。

        断开时只存已经吐出来的字，不标「已中断」也不补占位：前端本来就会把这条
        当成正常回复渲染，多一个后缀只会污染下一轮的上下文。
        """
        nonlocal persisted
        answer = "".join(answer_parts).strip()
        if not persisted and (answer or tool_calls):
            persisted = True
            async with AsyncSessionLocal() as db:
                await session_service.append_message(
                    db,
                    sid,
                    user_id,
                    role="assistant",
                    content=answer,
                    tool_calls=tool_calls,
                    turn_id=turn_id,
                )
                await session_service.record_turn_usage(
                    db,
                    turn_id,
                    usage_events=usage_events,
                    platform=agent.platform,
                    model=agent.model_name,
                )
        return answer

    try:
        astream_kwargs: dict[str, Any] = {
            "system_prompt": agent_prompt,
            "thinking": use_thinking,
        }
        if tool_names is not None:
            astream_kwargs["tool_names"] = tool_names
        async for event in agent.astream(history, **astream_kwargs):
            kind = event["type"]

            if kind == "usage":
                usage_events.append(event)

            elif kind == "token":
                answer_parts.append(event["text"])

            elif kind == "tool_start":
                tool = event.get("tool", "")
                call_id = event.get("call_id", "")
                call = _new_tool_call(tool, call_id)
                call["input"] = event.get("input") or {}
                tool_calls.append(call)
                pending_tools[_tool_key(tool, call_id)] = call

            elif kind == "citations":
                call = _find_tool_call(
                    _tool_key(event.get("tool", ""), event.get("call_id", ""))
                )
                if call is not None:
                    call["citations"].extend(event.get("items") or [])

            elif kind == "tool_end":
                tool = event.get("tool", "")
                call_id = event.get("call_id", "")
                key = _tool_key(tool, call_id)
                call = pending_tools.pop(key, None) or _find_tool_call(key)
                if call is None:  # 乱序容错：没收到 start 也按 end 补一条
                    call = _new_tool_call(tool, call_id)
                    tool_calls.append(call)
                call.update(
                    tool_name=tool or call.get("tool_name", ""),
                    call_id=call_id or call.get("call_id", ""),
                    result=event.get("result") or event.get("preview") or "",
                    preview=event.get("preview", ""),
                    duration_ms=event.get("duration_ms"),
                )

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


# 兼容 router / 测试里的既有导入名；函数实现以 astream_chat 为准
stream_chat = astream_chat
