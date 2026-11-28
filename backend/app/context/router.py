"""上下文段管理接口。

agent 绑定 / agent 文档：管理员维护。
user 文档：当前用户只能管理自己的资料。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service as agent_service
from app.chat.chat_manager import ChatConfigError
from auth.database import get_db
from auth.deps import get_current_admin, get_current_user
from auth.models import User

from . import composer
from . import service as context_service
from .schemas import (
    AgentContextBindingCreate,
    ContextGenerateRequest,
    ContextGenerateResponse,
    AgentContextBindingOut,
    AgentContextBindingUpdate,
    AgentContextDocCreate,
    AgentContextDocOut,
    AgentContextDocUpdate,
    AgentMemoryCreate,
    AgentMemoryOut,
    AgentMemoryUpdate,
    SystemPromptComposeRequest,
    SystemPromptComposeResponse,
    UserContextDocCreate,
    UserContextDocOut,
    UserContextDocUpdate,
)

router = APIRouter(prefix="/context", tags=["context"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, context_service.ContextConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(
        exc,
        (context_service.ContextNotFound, agent_service.AgentNotFound),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise exc


async def _ensure_agent(db: AsyncSession, agent_id: int | None) -> None:
    if agent_id is not None:
        await agent_service.get_agent(db, agent_id)


# ---------------- Agent bindings ----------------

@router.get(
    "/agent-bindings",
    response_model=list[AgentContextBindingOut],
    summary="agent 上下文绑定列表（管理员）",
)
async def list_agent_bindings(
    agent_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentContextBindingOut]:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.list_bindings(db, agent_id)
    except (context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agent-bindings",
    response_model=AgentContextBindingOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增 agent 上下文绑定（管理员）",
)
async def create_agent_binding(
    agent_id: int,
    payload: AgentContextBindingCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentContextBindingOut:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.create_binding(db, agent_id, payload)
    except (
        context_service.ContextConflict,
        context_service.ContextNotFound,
        agent_service.AgentNotFound,
    ) as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/agent-bindings/{binding_id}",
    response_model=AgentContextBindingOut,
    summary="修改 agent 上下文绑定（管理员）",
)
async def update_agent_binding(
    binding_id: int,
    payload: AgentContextBindingUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentContextBindingOut:
    try:
        return await context_service.update_binding(db, binding_id, payload)
    except (context_service.ContextConflict, context_service.ContextNotFound) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agent-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 agent 上下文绑定（管理员）",
)
async def delete_agent_binding(
    binding_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await context_service.delete_binding(db, binding_id)
    except context_service.ContextNotFound as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- Agent docs ----------------

@router.get(
    "/agent-docs",
    response_model=list[AgentContextDocOut],
    summary="agent 文档列表（管理员）",
)
async def list_agent_docs(
    agent_id: int | None = None,
    include_global: bool = True,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentContextDocOut]:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.list_agent_docs(db, agent_id, include_global=include_global)
    except (context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agent-docs",
    response_model=AgentContextDocOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增 agent 文档（管理员）",
)
async def create_agent_doc(
    payload: AgentContextDocCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentContextDocOut:
    try:
        await _ensure_agent(db, payload.agent_id)
        return await context_service.create_agent_doc(db, payload)
    except (
        context_service.ContextConflict,
        context_service.ContextNotFound,
        agent_service.AgentNotFound,
    ) as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/agent-docs/{doc_id}",
    response_model=AgentContextDocOut,
    summary="修改 agent 文档（管理员）",
)
async def update_agent_doc(
    doc_id: int,
    payload: AgentContextDocUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentContextDocOut:
    try:
        return await context_service.update_agent_doc(db, doc_id, payload)
    except (context_service.ContextConflict, context_service.ContextNotFound) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agent-docs/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 agent 文档（管理员）",
)
async def delete_agent_doc(
    doc_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await context_service.delete_agent_doc(db, doc_id)
    except context_service.ContextNotFound as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- User docs ----------------

@router.get(
    "/user-docs",
    response_model=list[UserContextDocOut],
    summary="我的上下文文档",
)
async def list_user_docs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserContextDocOut]:
    return await context_service.list_user_docs(db, current_user.id)


@router.post(
    "/user-docs",
    response_model=UserContextDocOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增我的上下文文档",
)
async def create_user_doc(
    payload: UserContextDocCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserContextDocOut:
    try:
        return await context_service.create_user_doc(db, current_user.id, payload)
    except context_service.ContextConflict as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/user-docs/{doc_id}",
    response_model=UserContextDocOut,
    summary="修改我的上下文文档",
)
async def update_user_doc(
    doc_id: int,
    payload: UserContextDocUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserContextDocOut:
    try:
        return await context_service.update_user_doc(db, current_user.id, doc_id, payload)
    except (context_service.ContextConflict, context_service.ContextNotFound) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/user-docs/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除我的上下文文档",
)
async def delete_user_doc(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await context_service.delete_user_doc(db, current_user.id, doc_id)
    except context_service.ContextNotFound as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- LLM 生成上下文内容 ----------------

@router.post(
    "/generate",
    response_model=ContextGenerateResponse,
    summary="用 LLM 生成上下文段内容（管理员）",
)
async def generate_context(
    payload: ContextGenerateRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ContextGenerateResponse:
    try:
        content = await composer.generate_section_content(
            db,
            agent_id=payload.agent_id,
            kind=payload.kind,
            current=payload.current,
            hint=payload.hint,
            variant=payload.variant,
        )
        return ContextGenerateResponse(content=content)
    except (agent_service.AgentNotFound, context_service.ContextNotFound) as exc:
        raise _http_error(exc) from exc
    except ChatConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"生成失败：{exc.__class__.__name__}: {exc}",
        ) from exc


@router.post(
    "/compose-system-prompt",
    response_model=SystemPromptComposeResponse,
    summary="按运行时规则拼出最终系统提示词（管理员）",
)
async def compose_system_prompt(
    payload: SystemPromptComposeRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> SystemPromptComposeResponse:
    """按 Agent 预设保存的 binding 顺序拼提示词；取数与拼装由 composer 负责。"""
    try:
        content = await composer.compose_system_prompt(
            db,
            prompt=payload.prompt,
            agent_id=payload.agent_id,
            user_id=current_user.id,
        )
    except agent_service.AgentNotFound as exc:
        raise _http_error(exc) from exc
    return SystemPromptComposeResponse(content=content)


# ---------------- Agent memories ----------------

@router.get(
    "/agent-memories",
    response_model=list[AgentMemoryOut],
    summary="agent 长期记忆列表（管理员）",
)
async def list_memories(
    agent_id: int,
    user_id: int | None = Query(default=None, ge=0, description="不传=全部；0=agent 全局"),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentMemoryOut]:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.list_agent_memories(db, agent_id, user_id=user_id)
    except (context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agent-memories",
    response_model=AgentMemoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增 agent 长期记忆（管理员）",
)
async def create_memory(
    agent_id: int,
    payload: AgentMemoryCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentMemoryOut:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.create_agent_memory(db, agent_id, payload)
    except (context_service.ContextConflict, context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/agent-memories/{memory_id}",
    response_model=AgentMemoryOut,
    summary="修改 agent 长期记忆（管理员）",
)
async def update_memory(
    memory_id: int,
    agent_id: int,
    payload: AgentMemoryUpdate,
    user_id: int | None = Query(default=None, ge=0, description="不传=不限制用户范围"),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentMemoryOut:
    try:
        await _ensure_agent(db, agent_id)
        return await context_service.update_agent_memory(
            db, agent_id, memory_id, payload, user_id=user_id
        )
    except (context_service.ContextConflict, context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agent-memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 agent 长期记忆（管理员）",
)
async def delete_memory(
    memory_id: int,
    agent_id: int,
    user_id: int | None = Query(default=None, ge=0, description="不传=不限制用户范围"),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await _ensure_agent(db, agent_id)
        await context_service.delete_agent_memory(db, agent_id, memory_id, user_id=user_id)
    except (context_service.ContextNotFound, agent_service.AgentNotFound) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
