"""会话与消息 ORM 模型（落库到 MySQL）

复用 auth 模块的 SQLAlchemy Base 与异步引擎（同一套数据库），
使 Alembic autogenerate 能把这两张表纳入版本管理，风格与 settings/models.py 一致。

关系：chat_sessions 1 —— N chat_messages，删除会话时级联清掉消息。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auth.database import Base


class ChatSession(Base):
    """一次连续对话的容器；同一用户可并行多个会话"""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 归属工作区；NULL = 未分组。删除工作区时会话保留（SET NULL）
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True, default=None
    )
    # 会话标题：首条用户消息自动截取，也支持前端改名
    title: Mapped[str] = mapped_column(String(255), default="")
    # 记录会话使用的平台与模型，便于重开对话时恢复上下文配置
    platform: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    # active / archived，归档不出现在默认列表
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), index=True
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<ChatSession id={self.id} user_id={self.user_id} title={self.title!r}>"


class ChatMessage(Base):
    """会话内的一条消息；role 与 OpenAI / langchain 的取值对齐"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    # user / assistant / system / tools
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # 一轮问答的标识：取该轮 user 消息 id；assistant / 工具行都回指它，老数据为 NULL
    turn_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    # role=tools 时记录工具名；assistant 发起的 tool_call 名称也写这里
    tool_name: Mapped[str] = mapped_column(String(128), default="")
    # 本次消息的 token 用量，0 表示未统计
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<ChatMessage id={self.id} session_id={self.session_id} role={self.role}>"


class ChatToolCall(Base):
    """一次工具调用；从 chat_messages.segments 里拆出来便于查询与统计"""

    __tablename__ = "chat_tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    # 发出这次工具调用的 assistant 消息；消息删除时由 FK 级联清理
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    # 与 assistant 消息相同，取该轮 user 消息 id
    turn_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    # 本轮内的全局顺序，以及它归属的 assistant segment_id
    seq: Mapped[int] = mapped_column(Integer, default=0)
    segment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    # 模型侧 tool_call_id；上游不返回时为空串，配对退化到 tool_name
    call_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_text: Mapped[str] = mapped_column(Text, default="")
    # 给前端展开区用的截断摘要，完整结果在 result_text
    preview: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citations_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<ChatToolCall id={self.id} tool={self.tool_name!r} call_id={self.call_id!r}>"
