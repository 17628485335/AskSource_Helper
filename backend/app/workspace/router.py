"""工作区相关路由（均需登录，且只能操作自己的工作区）

- GET    /workspaces          列表（首个为空的用户自动初始化「个人空间」）
- POST   /workspaces          新建
- PATCH  /workspaces/{id}     改名 / 改描述
- DELETE /workspaces/{id}     删除（其下会话解挂回未归属，默认区不可删）

跨用户访问统一返回 404，不暴露工作区是否存在；业务约束违规返回 422。
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_user
from auth.models import User

from . import service
from .schemas import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate

# 路径已含 /workspaces 前缀，此处不再设 prefix（与 session/router.py 同风格）
router = APIRouter(tags=["workspace"])


def _to_out(ws, count: int) -> WorkspaceOut:
    out = WorkspaceOut.model_validate(ws)
    out.session_count = count
    return out


@router.get(
    "/workspaces",
    response_model=list[WorkspaceOut],
    summary="查询我的工作区列表",
)
async def read_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceOut]:
    rows = await service.list_workspaces(db, current_user.id)
    counts = await service.session_counts(db, current_user.id)
    return [_to_out(w, counts.get(w.id, 0)) for w in rows]


@router.post(
    "/workspaces",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建工作区",
)
async def add_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    try:
        ws = await service.create_workspace(
            db, user_id=current_user.id, name=payload.name, description=payload.description
        )
    except service.WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _to_out(ws, 0)


@router.patch(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceOut,
    summary="修改工作区",
)
async def modify_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    if payload.name is None and payload.description is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="至少提供 name 或 description",
        )
    ws = await service.update_workspace(
        db, workspace_id, current_user.id, name=payload.name, description=payload.description
    )
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工作区不存在")
    counts = await service.session_counts(db, current_user.id)
    return _to_out(ws, counts.get(ws.id, 0))


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除工作区",
)
async def remove_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        ok = await service.delete_workspace(db, workspace_id, current_user.id)
    except service.WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工作区不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
