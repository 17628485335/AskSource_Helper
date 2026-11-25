"""工作区 ORM 模型

复用 auth 模块的 SQLAlchemy Base 与异步引擎（同一套数据库），
使 Alembic autogenerate 能把本表纳入版本管理，风格与 settings/models.py 一致。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from auth.database import Base


class Workspace(Base):
    """用户级工作区：会话的分组容器"""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    # 默认工作区（「个人空间」）：首个未分组会话自动归入，不可删除
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Workspace id={self.id} user_id={self.user_id} name={self.name!r}>"
