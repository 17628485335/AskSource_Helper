"""Agent 与提示词版本管理接口。

普通登录用户可读 agent 列表；写操作与提示词历史仅管理员可用。
提示词/模型/工具配置在下一轮对话读库生效，不需要 reload 模型池。
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_admin, get_current_user
from auth.models import User

from . import service as agent_service
from .schemas import (
    AgentCreate,
    AgentOut,
    AgentPromptCreate,
    AgentPromptOut,
    AgentUpdate,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, agent_service.AgentKeyExists):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (agent_service.AgentNotFound, agent_service.PromptNotFound)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise exc


@router.get("", response_model=list[AgentOut], summary="agent 列表（登录可读）")
async def list_agents(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentOut]:
    return await agent_service.list_agents(db, active_only=not include_inactive)


@router.get("/{agent_id}", response_model=AgentOut, summary="agent 定义（登录可读）")
async def read_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        return await agent_service.get_agent(db, agent_id)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建 agent（管理员）",
)
async def create_agent(
    payload: AgentCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        return await agent_service.create_agent(db, payload)
    except (
        agent_service.AgentNotFound,
        agent_service.AgentKeyExists,
        agent_service.PromptNotFound,
    ) as exc:
        raise _http_error(exc) from exc


@router.patch("/{agent_id}", response_model=AgentOut, summary="改 agent 配置（管理员）")
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        return await agent_service.update_agent(db, agent_id, payload)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除 agent（管理员）")
async def delete_agent(
    agent_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await agent_service.delete_agent(db, agent_id)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{agent_id}/prompts",
    response_model=list[AgentPromptOut],
    summary="提示词版本历史（管理员）",
)
async def list_prompts(
    agent_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentPromptOut]:
    try:
        return await agent_service.list_prompts(db, agent_id)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{agent_id}/prompts",
    response_model=AgentPromptOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增提示词版本（管理员）",
)
async def create_prompt(
    agent_id: int,
    payload: AgentPromptCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentPromptOut:
    try:
        return await agent_service.create_prompt(db, agent_id, payload)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{agent_id}/prompts/{version}/activate",
    response_model=AgentOut,
    summary="切换生效提示词版本（管理员）",
)
async def activate_prompt(
    agent_id: int,
    version: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        return await agent_service.activate_prompt(db, agent_id, version)
    except (agent_service.AgentNotFound, agent_service.PromptNotFound) as exc:
        raise _http_error(exc) from exc
