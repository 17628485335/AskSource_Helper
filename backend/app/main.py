"""Backend 应用入口（FastAPI）

auth 为独立顶层包（backend/auth），与 app 平级；从 backend/ 目录运行时可直接导入。
"""

from fastapi import FastAPI

from auth import router as auth_router

from .settings.router import router as settings_router

app = FastAPI(title="AskSource Helper API", version="0.1.0")

# 挂载认证路由（/auth/register、/auth/login、/auth/me）
app.include_router(auth_router)

# 挂载设置路由（/settings/model-providers）
app.include_router(settings_router)


@app.get("/", tags=["health"])
def health() -> dict[str, str]:
    """健康检查"""
    return {"status": "ok"}


def main() -> None:
    """开发启动：uvicorn app.main:app --reload 亦可"""
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
