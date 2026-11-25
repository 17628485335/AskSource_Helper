"""Chat 端点的前后端流式通信协议：agent.astream_events(v2) → SSE 事件字典

协议（一轮对话的帧序列，meta/done/error 由 service 层负责，不在本模块）：

| 事件 | 载荷 | 前端行为 | astream_events 来源 |
|------|------|----------|---------------------|
| token | {"text"} | 拼进回答正文（也进落库 buffer） | on_chat_model_stream 的 content 增量 |
| reasoning | {"text"} | 渲染到可折叠「思考过程」块，不进正文不落库 | on_chat_model_stream chunk.additional_kwargs.reasoning_content |
| tool_start | {"tool","input"} | 工具徽标置「执行中」 | 模型流里首个带该工具名的 tool_call_chunk（早于真正执行，UI 能提前亮） |
| tool_end | {"tool","preview"} | 徽标置「完成」，preview 供展开查看 | on_tool_end |
| citations | {"tool","items"} | 来源卡片按 index 去重累加 | on_tool_end 的 ToolMessage.artifact |

为什么事件从 astream(stream_mode="messages") 换成 astream_events：
- messages 模式只给 (消息块, metadata) 二元组，工具「开始执行 / 执行完成 / 入参是什么」
  全看不到——旧协议只能从 tool_call_chunks 播报一个名字，前端 case 'tool' 甚至接不到
  （后端事件名是 tools），工具状态一直是坏的。astream_events 有完整的 on_tool_start /
  on_tool_end 生命周期，run_id 还能把 start 和 end 配对。
- context kwarg 实测原样到达图中间件（request.runtime.context），
  「一份图服务两种思考态」的 select_thinking 切换不受影响。

注意事项（都有实测依据，改之前先重跑探针）：
- reasoning_content 不是 langchain 标准字段，靠 settings.llm.ReasoningChatOpenAI 覆写
  _convert_chunk_to_generation_chunk 挂进 additional_kwargs 才会出现在 stream 事件的 chunk 上；
  换上游适配器时那一层不能丢。
- on_chat_model_end 带整段聚合消息，正文已逐块流过，不能再重发，否则 done 里全文翻倍。
- 引用工具与协议解耦：只有 web_search / read_url 这类工具才带 artifact，
  普通工具返回 str 时 preview 直接取 str，不产生 citations 帧。
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, ToolMessage

from app.tools.citations import extract_citations

# 事件名清单：service / router / 前端据此对齐，新增事件先加这里
EVENT_TYPES = ("token", "reasoning", "tool_start", "tool_end", "citations")

# tool_end.preview 的截断长度：够前端 tooltip/展开区用，又不会把整页搜索原文推过网络
PREVIEW_CHARS = 400


def _text_of(content: Any) -> str:
    """消息 content 容错取值：str 或分块 list（推理模型的多模态形状）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


def _preview_of(output: Any) -> str:
    """工具结果的展示摘要：ToolMessage 取 content，dict 取字符串化，其余 str 兜底"""
    if isinstance(output, BaseMessage):
        text = _text_of(output.content)
    elif isinstance(output, dict):
        for value in output.values():
            if isinstance(value, ToolMessage):
                text = _text_of(value.content)
                break
        else:
            text = str(output)
    else:
        text = str(output)
    text = text.strip()
    return text[:PREVIEW_CHARS]


async def translate(
    agent: Any,
    messages: Sequence[Any],
    *,
    context: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """把 create_agent 图的 astream_events(v2) 逐个翻译成协议事件字典。

    只管翻译：不碰数据库、不发 meta/done/error（那三个是 service 的编排职责），
    异常原样抛出，由调用方转成 error 事件。

    announced（已播报的工具名）必须是生成器局部状态：同一个 ModelAgent 实例会被
    并发请求复用，挂到 self 上会让后一个请求看不到前一个请求播报过的工具名。
    """
    announced: set[str] = set()
    async for ev in agent.astream_events(
        {"messages": list(messages)}, version="v2", context=context or {}
    ):
        kind = ev["event"]

        if kind == "on_chat_model_stream":
            chunk = (ev.get("data") or {}).get("chunk")
            if not isinstance(chunk, AIMessageChunk):
                continue
            # 思考增量：由 settings.llm.ReasoningChatOpenAI 从 delta 里接住，父类会直接丢掉
            reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                yield {"type": "reasoning", "text": reasoning}
            # 工具名在模型流里一出现就播报，不等 on_tool_start：ReAct 从决定调用到
            # 工具真正跑起来之间还有一段静默，UI 提前亮徽标才不会像卡死
            for call in getattr(chunk, "tool_call_chunks", None) or []:
                name = call.get("name") if isinstance(call, dict) else None
                if name and name not in announced:
                    announced.add(name)
                    yield {"type": "tool_start", "tool": name, "input": {}}
            text = _text_of(chunk.content)
            if text:
                yield {"type": "token", "text": text}

        elif kind == "on_tool_start":
            # 兜底：若模型流里没露出工具名（个别上游 tool_call_chunks 不带 name），
            # 执行开始事件是唯一能报名字的时机；已播报过的不重发
            name = ev.get("name") or ""
            if name and name not in announced:
                announced.add(name)
                data = ev.get("data") or {}
                yield {"type": "tool_start", "tool": name, "input": data.get("input") or {}}

        elif kind == "on_tool_end":
            name = ev.get("name") or ""
            output = (ev.get("data") or {}).get("output")
            # 引用来自 ToolMessage.artifact：工具的旁路结构化数据，不会发给模型。
            # 必须先于 tool_end 发，前端收到徽标「完成」时来源卡片已在路上
            if isinstance(output, ToolMessage):
                items = extract_citations(output)
                if items:
                    yield {"type": "citations", "tool": name, "items": items}
            yield {"type": "tool_end", "tool": name, "preview": _preview_of(output)}
