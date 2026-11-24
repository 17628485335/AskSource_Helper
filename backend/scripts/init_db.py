"""数据库初始化脚本：创建目标数据库（若不存在）

用途：在执行 Alembic 迁移之前，确保 DATABASE_URL 指向的数据库已存在。
Alembic 的迁移只能建表，不能建库，因此单独提供本步骤。

用法（在 backend/ 目录下）：
    python -m scripts.init_db
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from auth.config import get_settings


async def main() -> None:
    url = make_url(get_settings().database_url)
    db_name = url.database
    if not db_name:
        raise SystemExit("DATABASE_URL 未包含数据库名，无法建库")

    # 显式重建不含库名的服务器连接串（url.set(database=None) 不会清空 database）
    # CREATE DATABASE 不能在事务内执行，故用 AUTOCOMMIT
    server_url = URL.create(
        drivername=url.drivername,
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        query=dict(url.query),
    )
    # 注意：不要把 URL 再 str()，SQLAlchemy 的 str(url) 会把密码掩码成 ***
    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
        print(f"[init_db] 数据库已就绪：{db_name}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
