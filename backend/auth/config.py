"""认证模块配置

优先从环境变量 / auth 目录下的独立配置 auth/.env 读取，未设置时使用便于本地开发的默认值。
生产环境务必覆盖 jwt_secret_key 与 database_url。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# auth 独立配置文件：始终相对本文件定位，不受启动目录影响
_AUTH_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_AUTH_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库连接串（SQLAlchemy 异步 + aiomysql）
    database_url: str = (
        "mysql+aiomysql://root:root@127.0.0.1:3306/asksource?charset=utf8mb4"
    )

    # JWT 配置（下方仅为开发默认值，生产必须通过环境变量覆盖）
    jwt_secret_key: str = "dev-only-insecure-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例"""
    return Settings()
