"""工作区服务：CRUD 与默认工作区初始化

职责边界与 session/service.py 相同：只做数据读写，不掺 HTTP 语义。
与 chat_sessions 的关联约定：
- 删除工作区 → 会话的 workspace_id 置 NULL（不级联删会话）；
- 首次为空的用户自动建一个「个人空间」，并把存量未归属会话回填进去，
  保证 UI 上「所有会话都有归属」。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.session.models import ChatSession

from .models import Workspace

DEFAULT_NAME = "个人空间"
# 防滥用：单用户工作区数量上限
MAX_PER_USER = 20


class WorkspaceError(RuntimeError):
    """业务约束不满足（数量超限、默认区不可删等），由 router 转成可读错误"""


async def get_owned(db: AsyncSession, workspace_id: int, user_id: int) -> Workspace | None:
    """按 id 取工作区并校验归属；不属于该用户一律视为不存在"""
    return await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
    )


async def default_workspace(db: AsyncSession, user_id: int) -> Workspace | None:
    """取用户的默认工作区（没有则返回 None，不在此处隐式创建）"""
    return await db.scalar(
        select(Workspace).where(
            Workspace.user_id == user_id, Workspace.is_default == True  # noqa: E712
        ).limit(1)
    )


async def list_workspaces(db: AsyncSession, user_id: int) -> list[Workspace]:
    """列出用户的全部工作区；一个都没有时先初始化默认「个人空间」"""
    rows = await db.scalars(
        select(Workspace)
        .where(Workspace.user_id == user_id)
        .order_by(Workspace.id.asc())
    )
    items = list(rows.all())
    if items:
        return items

    ws = Workspace(user_id=user_id, name=DEFAULT_NAME, is_default=True)
    db.add(ws)
    await db.flush()  # 先拿到自增 id，供回填语句使用
    # 存量未归属会话回填进默认工作区，避免「旧对话凭空消失」
    await db.execute(
        update(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.workspace_id.is_(None))
        .values(workspace_id=ws.id)
    )
    await db.commit()
    # commit 会让实例属性过期，异步会话下再读会触发 MissingGreenlet，刷新一次
    await db.refresh(ws)
    return [ws]


async def session_counts(db: AsyncSession, user_id: int) -> dict[int, int]:
    """统计各工作区下的会话数，供列表接口回填"""
    rows = await db.execute(
        select(ChatSession.workspace_id, func.count())
        .where(ChatSession.user_id == user_id, ChatSession.workspace_id.isnot(None))
        .group_by(ChatSession.workspace_id)
    )
    return {wid: int(n) for wid, n in rows.all() if wid is not None}


async def create_workspace(
    db: AsyncSession, *, user_id: int, name: str, description: str = ""
) -> Workspace:
    total = await db.scalar(
        select(func.count()).select_from(Workspace).where(Workspace.user_id == user_id)
    )
    if int(total or 0) >= MAX_PER_USER:
        raise WorkspaceError(f"工作区数量已达上限（{MAX_PER_USER} 个）")

    ws = Workspace(user_id=user_id, name=name.strip()[:128], description=description.strip()[:512])
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def update_workspace(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Workspace | None:
    ws = await get_owned(db, workspace_id, user_id)
    if ws is None:
        return None
    if name is not None:
        ws.name = name.strip()[:128]
    if description is not None:
        ws.description = description.strip()[:512]
    await db.commit()
    await db.refresh(ws)
    return ws


async def delete_workspace(db: AsyncSession, workspace_id: int, user_id: int) -> bool:
    """删除工作区；先解挂其下会话（置 NULL），默认工作区不可删"""
    ws = await get_owned(db, workspace_id, user_id)
    if ws is None:
        return False
    if ws.is_default:
        raise WorkspaceError("默认工作区不可删除")

    await db.execute(
        update(ChatSession)
        .where(ChatSession.workspace_id == ws.id)
        .values(workspace_id=None)
    )
    await db.delete(ws)
    await db.commit()
    return True


async def resolve_owned_id(
    db: AsyncSession, user_id: int, workspace_id: int | None
) -> int | None:
    """把对话请求的 workspace 入参解析成最终归属 id。

    - 传了 id：校验归属，不属于该用户抛 WorkspaceError（而不是静默忽略，避免会话悄悄进错组）；
    - 没传（None）：回落到默认工作区，连默认都没有则保持 NULL。
    """
    if workspace_id is None:
        ws = await default_workspace(db, user_id)
        return ws.id if ws else None
    ws = await get_owned(db, workspace_id, user_id)
    if ws is None:
        raise WorkspaceError("工作区不存在")
    return ws.id
