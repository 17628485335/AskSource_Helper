"""LLM 提供商 ORM 模型

复用 auth 模块的 SQLAlchemy Base 与异步引擎（同一套数据库），
使 Alembic autogenerate 能把本表纳入版本管理。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from auth.database import Base


class LlmProvider(Base):
    """用户级 LLM 平台接入配置"""

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), default="")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    api_key: Mapped[str] = mapped_column(String(512), default="")
    default_model: Mapped[str] = mapped_column(String(128), default="")
    # 模型上下文窗口（token），用于裁剪送进模型的对话历史
    context_size: Mapped[int] = mapped_column(Integer, default=32768)
    supports_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<LlmProvider id={self.id} user_id={self.user_id} platform={self.platform}>"
