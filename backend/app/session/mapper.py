"""会话响应 DTO 映射：把 ORM 消息行、工具调用、轮次用量组装成 MessageOut。

纯映射，不碰数据库；router 只负责取数与权限校验。
"""

from .models import ChatMessage, ChatToolCall, ChatTurn
from .schemas import MessageOut, ToolCallOut, TurnUsageOut


def to_message_outs(
    rows: list[ChatMessage],
    tool_rows: list[ChatToolCall],
    turns: dict[int, ChatTurn],
) -> list[MessageOut]:
    """按消息行顺序组装响应，工具调用与轮次用量按 id 挂到对应消息上。"""
    tools_by_message: dict[int, list[ToolCallOut]] = {}
    for tool in tool_rows:
        tools_by_message.setdefault(tool.message_id, []).append(
            ToolCallOut.model_validate(tool)
        )

    out: list[MessageOut] = []
    for row in rows:
        usage: TurnUsageOut | None = None
        if row.turn_id in turns:
            turn = turns[row.turn_id]
            usage = TurnUsageOut(
                input_tokens=turn.input_tokens,
                output_tokens=turn.output_tokens,
                total_tokens=turn.total_tokens,
                last_input_tokens=turn.last_input_tokens or 0,
                input_token_details=turn.input_token_details or {},
                output_token_details=turn.output_token_details or {},
                model_calls=turn.model_calls,
            )
        out.append(
            MessageOut.model_validate(row).model_copy(
                update={
                    "tool_calls": tools_by_message.get(row.id, []),
                    "turn_usage": usage,
                }
            )
        )
    return out
