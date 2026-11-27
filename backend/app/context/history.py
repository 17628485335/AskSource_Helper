"""对话历史组装：把会话数据转成模型可用的 langchain 消息。

职责边界：
- app.session.service 只负责数据读写（ORM 消息行、摘要、工具调用）；
- 本模块负责转成 langchain 消息，并用 <message_summary> / <messages> 分块拼成上下文。

摘要原来是 SystemMessage，但 chat_manager.astream 会剔除历史里的 SystemMessage，
导致摘要根本进不了上下文。用 HumanMessage + XML 分段，摘要才不会丢。
"""

from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.session import service as session_service
from app.session.models import ChatMessage, ChatToolCall
from app.xml_blocks import join_blocks, xml_block

DEFAULT_HISTORY_LIMIT = session_service.DEFAULT_HISTORY_LIMIT

_ROLE_NAMES = {
    HumanMessage: "用户",
    AIMessage: "助手",
    SystemMessage: "系统",
    ToolMessage: "工具",
}


def to_lc_messages(rows: Sequence[ChatMessage]) -> list[Any]:
    """把 ORM 消息行转成 langchain 消息对象（惰性导入，未装 langchain 也不影响本模块导入）

    tools 角色跳过：chat_tool_calls 里已经保存了 call_id / result_text / input_json，
    但本函数只接收 ChatMessage 行，没有把 ChatToolCall 重建成 ToolMessage，
    也没有还原 AIMessage.tool_calls。孤立的 ToolMessage 缺少配对的 tool_call_id
    和前置 AIMessage.tool_calls，硬塞会被上游判为非法上下文。

    要恢复完整工具上下文，必须按 segment_id / seq 成对构造：
    AIMessage(tool_calls=[...]) + ToolMessage(tool_call_id=..., content=...)。
    """
    mapping = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}
    out: list[Any] = []
    for row in rows:
        cls = mapping.get(row.role)
        if cls is None:
            continue
        out.append(cls(content=row.content))
    return out


def wrap_history(summary_text: str, messages: list[Any]) -> list[Any]:
    """把摘要与历史消息分别用 <message_summary> / <messages> 包裹成一条普通消息。

    没有摘要时也用 <messages> 包裹历史，保证结构一致；两者都为空时原样返回。
    """
    summary_text = (summary_text or "").strip()
    rendered: list[str] = []
    for message in messages:
        role = _ROLE_NAMES.get(type(message), getattr(message, "type", "消息"))
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if isinstance(call, dict) and call.get("name"):
                rendered.append(f"{role}：调用工具 {call['name']}")
        content = str(getattr(message, "content", "") or "").strip()
        if content:
            rendered.append(f"{role}：{content}")

    sections: list[str] = []
    if summary_text:
        sections.append(xml_block("message_summary", summary_text))
    if rendered:
        sections.append(xml_block("messages", "\n\n".join(rendered)))
    if not sections:
        return messages
    return [HumanMessage(content=join_blocks(*sections))]


async def load_history(
    db: Any,
    session_id: int,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    before_id: int | None = None,
) -> list[Any]:
    """读会话历史并转成模型可用的消息列表。

    已摘要消息（is_summary=true）不进上下文；摘要与消息分块拼成一条普通消息。
    翻页（before_id）时不拼摘要，直接返回原始消息列表。
    """
    rows = await session_service.load_messages(db, session_id, limit=limit, before_id=before_id)
    messages = to_lc_messages([r for r in rows if not r.is_summary])
    if before_id is not None:
        return messages
    summary = await session_service.get_summary(db, session_id)
    return wrap_history(summary.content if summary is not None else "", messages)


async def load_history_with_tools(
    db: Any,
    session_id: int,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    before_id: int | None = None,
) -> list[Any]:
    """读历史并成对重建 AIMessage(tool_calls) + ToolMessage。

    与 to_lc_messages 不同：这里会带上 chat_tool_calls，按 (turn_id, tool_name)
    顺序把工具结果配对到对应的调用上。找不到配对的 tools 行直接跳过，避免孤立
    ToolMessage 导致上游校验失败。
    """
    all_rows = await session_service.load_messages(db, session_id, limit=limit, before_id=before_id)
    rows = [r for r in all_rows if not r.is_summary]
    assistant_ids = [row.id for row in rows if row.role == "assistant"]
    calls = await session_service.load_tool_calls(db, assistant_ids)

    calls_by_message: dict[int, list[ChatToolCall]] = defaultdict(list)
    for call in calls:
        calls_by_message[call.message_id].append(call)

    pending: dict[tuple[int | None, str], deque[ChatToolCall]] = defaultdict(deque)
    out: list[Any] = []
    for row in rows:
        if row.role == "user":
            out.append(HumanMessage(content=row.content))
        elif row.role == "system":
            out.append(SystemMessage(content=row.content))
        elif row.role == "assistant":
            message_calls = calls_by_message.get(row.id, [])
            tool_calls = [
                {
                    "name": call.tool_name,
                    "args": call.input_json or {},
                    "id": call.call_id or call.tool_name,
                }
                for call in message_calls
            ]
            out.append(AIMessage(content=row.content, tool_calls=tool_calls or None))
            for call in message_calls:
                pending[(row.turn_id, call.tool_name)].append(call)
        elif row.role == "tools":
            queue = pending.get((row.turn_id, row.tool_name))
            call = queue.popleft() if queue else None
            if call is None:
                continue
            out.append(ToolMessage(content=row.content, tool_call_id=call.call_id or call.tool_name))

    if before_id is not None:
        return out
    summary = await session_service.get_summary(db, session_id)
    return wrap_history(summary.content if summary is not None else "", out)
