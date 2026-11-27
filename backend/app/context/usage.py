"""会话上下文用量：把会话数据换算成模型窗口占用。

职责边界：app.session.service 只负责数据读写，本模块负责用 token_counter
估算、计算预算与来源；不反向让 session 依赖 context 的业务计算。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.session import service as session_service

from .token_counter import count_context_tokens, estimate_text_tokens


async def get_context_usage(
    db: AsyncSession, session_id: int, *, context_size: int
) -> dict:
    """估算会话当前对话上下文用量。

    口径与 app.context.history 保持一致：只算未摘要消息 + 摘要内容。
    优先用最近一轮 API 返回的真实上下文快照；没有 usage 记录时回退 tiktoken 估算。
    """
    rows = await session_service.load_unsummarized_messages(db, session_id)
    estimated = count_context_tokens(rows)

    summary = await session_service.get_summary(db, session_id)
    summary_chars = len(summary.content) if summary else 0
    if summary:
        estimated += estimate_text_tokens(summary.content)

    latest_turn = await session_service.load_latest_usage_turn(db, session_id)
    if latest_turn is not None:
        used = latest_turn.last_input_tokens + latest_turn.last_output_tokens
        source = "api"
    else:
        used = estimated
        source = "estimated"

    size = max(1, context_size)
    return {
        "used_tokens": used,
        "context_size": size,
        "remaining_tokens": max(0, size - used),
        "usage_ratio": round(min(used / size, 1.0), 4),
        "message_count": len(rows),
        "summary_chars": summary_chars,
        "source": source,
    }
