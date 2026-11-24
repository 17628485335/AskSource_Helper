"""认证模块（FastAPI + JWT + SQLAlchemy/MySQL）

对外暴露 router，供应用挂载：

    from auth import router as auth_router
    app.include_router(auth_router)
"""

from .router import router

__all__ = ["router"]
