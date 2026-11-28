"""Agent 上下文段的 ORM 模型。

分三层，避免把 agent 规则和用户数据混在一起：
- agent_context_bindings：agent 决定注入哪些段、顺序、预算、信任级别；
- agent_context_docs：agent 自己拥有的内容（agent_id=NULL 表示全局共享）；
- user_context_docs：用户自己的资料，按 user_id 隔离；
- agent_memories：agent 的长期记忆，按条管理，由管理员在 agent 预设里维护。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from auth.database import Base


class AgentContextBinding(Base):
    """agent 的上下文注入策略；只声明引用，不保存实际内容"""

    __tablename__ = "agent_context_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_agent_ctx_binding_agent_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128), default="")
    # agent_doc / user_doc / generated / memory / none
    resolver: Mapped[str] = mapped_column(String(32), default="none", index=True)
    # 指向 agent_context_docs.key / user_context_docs.key，或生成器名
    ref_key: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1000)
    # anchor / policy / data / generated：模型应当如何理解这段内容
    trust_level: Mapped[str] = mapped_column(String(32), default="data")
    # 上面信任级别对应的中文描述，跟随 binding 一起保存并在界面回显
    trust_hint: Mapped[str] = mapped_column(String(128), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AgentContextBinding agent={self.agent_id} key={self.key!r} resolver={self.resolver!r}>"


class AgentContextDoc(Base):
    """agent 拥有的上下文内容；agent_id=NULL 表示全站共享规则"""

    __tablename__ = "agent_context_docs"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_agent_ctx_doc_agent_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=True, default=None
    )
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    version_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AgentContextDoc agent={self.agent_id} key={self.key!r}>"


class UserContextDoc(Base):
    """用户自己的上下文内容；按 user_id 隔离，agent 只引用不拥有"""

    __tablename__ = "user_context_docs"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_ctx_doc_user_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    version_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<UserContextDoc user={self.user_id} key={self.key!r}>"


class AgentMemory(Base):
    """agent 的长期记忆；按条管理，每条是一段可独立启用/停用事实。

    user_id=0 表示 agent 全局记忆；非 0 时只属于该用户。
    """

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    # 不建 FK：0 是全局哨兵值，不是真实用户
    user_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AgentMemory agent={self.agent_id} id={self.id}>"
