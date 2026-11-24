"""Backend 应用入口（FastAPI）

auth 为独立顶层包（backend/auth），与 app 平级；从 backend/ 目录运行时可直接导入。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auth import router as auth_router
from auth.database import AsyncSessionLocal

from .chat import ChatManager
from .chat.router import router as chat_router
from .session.router import router as session_router
from .settings.router import router as settings_router
from .workspace.router import router as workspace_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预热模型池：管理员每接入一个模型就各建一个 ReAct 图。

    缺配置只记日志不抛，不能因为模型没配好就起不来服务（登录、会话都还得用）。
    预热失败或裸 TestClient(app)（不跑 lifespan）都不影响正确性：
    对话路径靠 ChatManager.get() 的懒构建兜底，管理员保存配置靠 ChatManager.reload() 重建。
    """
    try:
        async with AsyncSessionLocal() as db:
            pool = await ChatManager.get(db)
        logger.info("模型池预热完成：%s", pool)
    except Exception as exc:
        logger.warning("模型池预热失败，首次对话时会再试一次：%s: %s", exc.__class__.__name__, exc)
    yield


app = FastAPI(title="AskSource Helper API", version="0.1.0", lifespan=lifespan)

# 挂载认证路由（/auth/register、/auth/login、/auth/me）
app.include_router(auth_router)

# 挂载设置路由（/settings/model-providers）
app.include_router(settings_router)

# 挂载会话路由（/sessions、/sessions/{id}/messages）
app.include_router(session_router)

# 挂载对话路由（/chat，SSE 流式）
app.include_router(chat_router)

# 挂载工作区路由（/workspaces，会话分组）
app.include_router(workspace_router)


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
