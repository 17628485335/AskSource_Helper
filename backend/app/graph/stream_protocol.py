"""Chat 端点的流式事件协议（后端 ↔ 前端唯一契约）。

本模块**只放事件构造函数**：把一次流式回答要下发的每种事件定型成 ev_* 工厂，
返回的字典字段名即前端 StreamEvent 的契约。这里不掺杂任何消费 astream_events 的
逻辑 —— 那部分（从哪个事件、取哪个字段）在 app.chat.chat_manager.ModelAgent.stream。

新增事件必须三处同步更新：本文件的 ev_*、ModelAgent.stream、
frontend/src/api/chat.ts（及 stores/chat.ts 的消费分支）。

事件类型
--------
| type        | 载荷                          | 前端行为                          | astream_events 来源 |
|-------------|-------------------------------|-----------------------------------|---------------------|
| `segment_start` | segment_id                | 分段边界；前端忽略，后端据此分段落库 | on_chat_model_start |
| `token`     | text                          | 拼进回答正文（也进后端落库 buffer） | on_chat_model_stream 的 content 增量 |
| `reasoning` | text                          | 折叠「思考过程」块，不进正文不落库  | chunk.additional_kwargs.reasoning_content |
| `tool_start`| tool, call_id, input          | 按 call_id 建工具徽标置「执行中」   | on_chat_model_end 装配好的 AIMessage.tool_calls |
| `tool_end`  | tool, call_id, preview, result, duration_ms | 徽标按 call_id 翻「完成」，preview 供展开查看，result 是完整调用结果（落库用），duration_ms 为工具耗时 | on_tool_end |
| `citations` | tool, call_id, items          | 来源卡片按 index 去重累加           | on_tool_end 的 ToolMessage.artifact |
| `usage`     | segment_id, input_tokens, output_tokens, total_tokens, input_token_details, output_token_details | 本段模型调用的 token 用量，后端汇总落 chat_turn | on_chat_model_end 的 AIMessage.usage_metadata |

（meta / done / error 由 app.chat.service 编排，不经本模块。）

tool_start 为什么取自 on_chat_model_end 而非模型流/on_tool_start：
- call_id 与完整入参只在装配好的 AIMessage.tool_calls 里同时齐备（实测）；模型流里的
  tool_call_chunks 把 args 切成 JSON 碎片、上游 index 还可能为 None，自行拼接不可靠；
- on_tool_start 的 data 只有 input、没有 tool_call_id，并行同名调用时 input 还可能是空 {}；
- 真正的 tool_call_id 要等到 on_tool_end 的 output.tool_call_id，故 tool_end/citations 也带
  call_id，前端据它把「开始/结束」配到同一枚徽标（并行同名不再被按名字合并）。

为什么用 astream_events 而非 astream(stream_mode="messages")：
- messages 模式只给 (消息块, metadata) 二元组，工具「开始执行 / 结束 / 入参」全看不到，
  旧协议只能从 tool_call_chunks 播报一个名字，前端甚至接不到（后端事件名是 tools 复数、
  前端 case 'tool' 单数），工具状态一直是坏的；astream_events 有完整的 on_tool_start /
  on_tool_end 生命周期。
- context kwarg 实测原样到达图中间件（request.runtime.context），
  「一份图服务两种思考态」的 select_thinking 切换不受影响。
"""

from __future__ import annotations

from typing import Any


def ev_segment_start(segment_id: int) -> dict[str, Any]:
    """构造 segment_start 事件：一次新的模型调用开始，后续 token/tool 事件属于该段。"""
    return {"type": "segment_start", "segment_id": segment_id}


def ev_token(text: str) -> dict[str, Any]:
    """构造 token 事件：推送模型回答正文的一个增量片段（后端也据此累加落库）。"""
    return {"type": "token", "text": text}


def ev_reasoning(text: str) -> dict[str, Any]:
    """构造 reasoning 事件：推送深度档的思考增量，前端收进折叠块，不进正文也不落库。"""
    return {"type": "reasoning", "text": text}


def ev_tool_start(tool: str, call_id: str = "", tool_input: Any = None) -> dict[str, Any]:
    """构造 tool_start 事件：工具开始执行。

    call_id 是模型侧的 tool_call_id（前端据此把 tool_end 配到同一枚徽标）；
    tool_input 是装配好的完整入参 dict。个别上游不返回 id 时 call_id 为空串，
    前端退化到按工具名匹配。
    """
    return {"type": "tool_start", "tool": tool, "call_id": call_id, "input": tool_input or {}}


def ev_tool_end(
    tool: str,
    preview: str,
    call_id: str = "",
    duration_ms: int | None = None,
    result: str = "",
) -> dict[str, Any]:
    """构造 tool_end 事件：工具执行结束，preview 是截断后的展示摘要，result 是完整调用结果。

    call_id 回指本次调用；duration_ms 是工具调用耗时（毫秒），拿不到开始时刻时为 None。
    result 供 service 按 segment 落库，前端展示仍用 preview，不把整段搜索原文推过网络。
    """
    return {
        "type": "tool_end",
        "tool": tool,
        "call_id": call_id,
        "preview": preview,
        "result": result,
        "duration_ms": duration_ms,
    }


def ev_citations(
    tool: str, items: list[dict[str, Any]], call_id: str = ""
) -> dict[str, Any]:
    """构造 citations 事件：工具返回的结构化引用，items[].index 与正文里的 [n] 同号。"""
    return {"type": "citations", "tool": tool, "call_id": call_id, "items": items}


def ev_usage(usage: dict[str, Any], *, segment_id: int) -> dict[str, Any]:
    """构造 usage 事件：一次模型调用的 token 用量，原样带上细分字段。

    usage 来自 AIMessage.usage_metadata，可能含 input_token_details /
    output_token_details（cache_read、reasoning 等）；上游没返回细分时缺省为空 dict。
    """
    return {
        "type": "usage",
        "segment_id": segment_id,
        "input_tokens": usage.get("input_tokens") or 0,
        "output_tokens": usage.get("output_tokens") or 0,
        "total_tokens": usage.get("total_tokens") or 0,
        "input_token_details": usage.get("input_token_details") or {},
        "output_token_details": usage.get("output_token_details") or {},
    }
