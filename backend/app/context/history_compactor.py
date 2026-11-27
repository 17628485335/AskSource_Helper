"""滑动窗口历史压缩器。

当前运行时还没有接入；本模块先把“怎么压、怎么摘要、怎么落库”定义清楚。

设计原则：
- 是否触发压缩由调用方判断（已算过 token），本模块被调用就直接压缩。
- 历史按“用户轮次”切分；只保留最近 2 轮原文，更早轮次交给 LLM 生成摘要。
- 摘要篇幅由 prompt 告诉模型，不在本地做字符/token 截断。
- 压缩结果直接落库：旧消息打 is_summary 标记 + 摘要独立写入 chat_summaries，
  下一轮由 app.context.history 用 <message_summary> 分块带进上下文。
"""

from typing import Any, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

# 最近 2 个用户轮次无条件保留，保证连续追问不丢上下文。
RECENT_TURNS_TO_KEEP = 2

# 摘要篇幅目标：写进 prompt 让 LLM 自己控制，不在本地硬截断。
SUMMARY_TARGET_CHARS = 500

SUMMARY_SYSTEM_PROMPT = f"""你是一个对话摘要助手。请把用户与助手之间较早的对话压缩成一段摘要。

要求：
- 用中文，控制在约 {SUMMARY_TARGET_CHARS} 字以内；内容重要时可适当放宽，但不要写成大段正文。
- 只保留对后续对话有用的事实、结论、决定与待办；去掉寒暄、重复和工具原始明细。
- 如果输入里带有「此前摘要」，把它一并纳入，不要丢掉其中仍然有效的信息。
- 不要编造原文没有的信息；没有值得保留的内容就如实说明。
- 只输出摘要正文，不要标题、不要 markdown 代码块。"""


def _split_rows_by_turn(rows: Sequence[Any]) -> list[list[Any]]:
    """按 role=user 把 ORM 行切成轮次。"""
    turns: list[list[Any]] = []
    current: list[Any] = []
    for row in rows:
        role = getattr(row, "role", "")
        if role == "user" and current:
            turns.append(current)
            current = []
        current.append(row)
    if current:
        turns.append(current)
    return turns


def _render_turns(dropped_turns: list[list[Any]], previous_summary: str) -> str:
    """把被丢弃的轮次渲染成给 LLM 的原文：工具明细不带正文，只标调用过。"""
    lines: list[str] = []
    if previous_summary:
        lines.append(f"此前摘要：\n{previous_summary}")
        lines.append("")
    for turn in dropped_turns:
        for row in turn:
            role = getattr(row, "role", "")
            content = str(getattr(row, "content", "") or "")
            if role == "user":
                lines.append(f"用户：{content}")
            elif role == "assistant":
                tool_name = str(getattr(row, "tool_name", "") or "")
                if tool_name:
                    lines.append(f"助手：调用工具 {tool_name}")
                if content.strip():
                    lines.append(f"助手：{content}")
            # tools 行是给模型看的检索结果，摘要里不需要原文
    return "\n".join(lines)


async def generate_summary(
    model: Any, dropped_turns: list[list[Any]], previous_summary: str = ""
) -> str:
    """把被丢弃的轮次交给 LLM 生成摘要；没有可摘要内容时返回空串。"""
    if not dropped_turns and not previous_summary:
        return ""
    response = await model.ainvoke(
        [
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            # 这里用 langchain HumanMessage，避免让 history_compactor 依赖 ORM 类型
            HumanMessage(content=_render_turns(dropped_turns, previous_summary)),
        ]
    )
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()


async def compact_history(
    db: Any,
    session_id: int,
    *,
    user_id: int,
    model: Any,
) -> None:
    """压缩会话历史并直接落库：保留最近 2 轮，更早轮次交给 LLM 生成摘要。

    是否触发压缩由调用方判断（已算过 token），本函数被调用就直接压缩。
    校验会话归属后读历史，打标 + 写 chat_summaries 在同一事务里完成。
    """
    # 延迟导入，保持 app.context 包初始化时不触发 session 子模块加载。
    from app.session import service as session_service

    session = await session_service.get_session(db, session_id, user_id)
    if session is None:
        raise LookupError("会话不存在或无权访问")

    # 读全表未摘要消息：limit 窗口外的旧轮次也参与摘要；已摘要行由 SQL 层过滤。
    rows = await session_service.load_unsummarized_messages(db, session_id)
    turns = _split_rows_by_turn(rows)
    if len(turns) <= RECENT_TURNS_TO_KEEP:
        return  # 没有更早轮次可压，不动库

    dropped_turns = turns[:-RECENT_TURNS_TO_KEEP]

    existing_summary = await session_service.get_summary(db, session_id)
    previous_summary = existing_summary.content if existing_summary else ""

    summary = await generate_summary(model, dropped_turns, previous_summary)
    if not summary:
        return

    # 只把更早轮次打 is_summary 标记（原文保留供翻看），摘要 upsert 到独立表。
    summarize_ids = {row.id for turn in dropped_turns for row in turn}
    model_name = getattr(model, "model_name", "") or getattr(model, "model", "") or ""
    await session_service.mark_summarized(
        db,
        session_id,
        user_id,
        message_ids=summarize_ids,
        summary=summary,
        model=str(model_name),
    )
