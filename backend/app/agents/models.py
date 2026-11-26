"""Agent 定义与提示词版本 ORM 模型（MySQL）。

agents 一条 = 一个可复用 agent；agent_prompts 多条 = 同一 agent 的提示词历史。
当前只有 chat agent；后续新增 agent 不必再改表结构。
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auth.database import Base


class Agent(Base):
    """Agent 定义：模型配置 + 工具白名单 + 当前生效的提示词版本"""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 稳定标识：chat / summary / planner ...；代码里按它查配置
    agent_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    # 模型配置；空串表示沿用请求里指定的平台/模型
    platform: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    # 工具白名单；NULL = 允许模型池里的全部工具，[] = 不允许任何工具
    tool_names_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    # 当前生效的 prompt 版本；agent_prompts 里可以留完整历史
    active_prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    prompts: Mapped[list["AgentPrompt"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Agent id={self.id} key={self.agent_key!r} active_v={self.active_prompt_version}>"


class AgentPrompt(Base):
    """提示词版本：只追加不原地改，便于回滚和排查线上回答"""

    __tablename__ = "agent_prompts"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_prompts_agent_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    system_prompt: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="prompts")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<AgentPrompt agent_id={self.agent_id} v={self.version}>"
