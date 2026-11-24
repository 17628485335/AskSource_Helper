"""数据库引擎与会话（异步）

create_async_engine 采用惰性连接，导入本模块不会强制连接 MySQL。
需使用异步驱动（aiomysql），连接串形如 mysql+aiomysql://...
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    # MySQL 容器默认走 UTC，而 created_at/updated_at 用的是 NOW()（server_default/onupdate），
    # 落库时间会比北京时间少 8 小时。这里在每条物理连接建立时把会话时区固定为 +08:00，
    # 使 NOW() 按北京墙钟计算；前端拿到不带时区的 naive 时间后按本地（东八区）解析也一致。
    # init_command 由驱动在 connect（含连接池重连）时执行，无需额外事件监听。
    connect_args={"init_command": "SET time_zone = '+08:00'"},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：请求级异步数据库会话，用完即关"""
    async with AsyncSessionLocal() as session:
        yield session
