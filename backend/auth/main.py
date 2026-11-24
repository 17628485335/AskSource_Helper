"""auth 微服务独立入口（FastAPI）

把认证路由单独挂载为一个可独立运行的服务，便于按微服务方式部署。
统一认证仍可由 app.main 聚合挂载；本模块只负责 auth 自身。

直接运行：python -m auth.main   或   uvicorn auth.main:app
注意：需从 backend/ 目录启动，以便 `auth` 包可导入且 .env 能被读取。
"""

from fastapi import FastAPI

from .router import router as auth_router

app = FastAPI(title="AskSource Auth Service", version="0.1.0")

# 挂载认证路由（/auth/register、/auth/login、/auth/me）
app.include_router(auth_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """健康检查"""
    return {"status": "ok", "service": "auth"}


def main() -> None:
    """开发启动：默认 127.0.0.1:8001，热重载"""
    import os

    import uvicorn

    host = os.getenv("AUTH_HOST", "127.0.0.1")
    port = int(os.getenv("AUTH_PORT", "8001"))
    reload = os.getenv("AUTH_RELOAD", "1") == "1"
    uvicorn.run("auth.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
