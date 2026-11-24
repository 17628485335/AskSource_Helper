"""设置相关路由

- /settings/model-providers：模型提供商下拉选项（静态）
- /settings/llm：当前用户的 LLM 配置读写（持久化到数据库，需登录）
"""

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_user
from auth.models import User

from .llm import MODEL_PROVIDERS, ProviderOption, resolve_base_url, test_provider_connection
from .models import LlmProvider
from .schemas import (
    LlmProvidersUpdate,
    ProviderOut,
    ProviderTestRequest,
    ProviderTestResult,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "/model-providers",
    response_model=list[ProviderOption],
    summary="获取模型提供商下拉选项",
)
async def list_model_providers() -> list[ProviderOption]:
    """返回可选的模型提供商（阿里百炼 / DeepSeek / 硅基流动）。

    base_url 经 resolve_base_url 处理：若环境变量（<平台>__BASE_URL）有覆盖则优先，
    否则用内置默认；供前端选择平台时预填。
    """
    return [
        ProviderOption(
            value=opt.value,
            label=opt.label,
            base_url=resolve_base_url(opt.value) or opt.base_url,
        )
        for opt in MODEL_PROVIDERS
    ]


@router.post(
    "/llm/test",
    response_model=ProviderTestResult,
    summary="测试 LLM 提供商连通性与密钥有效性",
)
async def test_llm_provider(
    payload: ProviderTestRequest,
    current_user: User = Depends(get_current_user),
) -> ProviderTestResult:
    """用提交的 base_url + api_key 探测一次（需登录，避免被当作开放代理）。"""
    result = await test_provider_connection(
        payload.base_url, payload.api_key, payload.default_model
    )
    return ProviderTestResult(**result)


async def _list_user_providers(
    db: AsyncSession, user_id: int
) -> list[LlmProvider]:
    result = await db.scalars(
        select(LlmProvider)
        .where(LlmProvider.user_id == user_id)
        .order_by(LlmProvider.id)
    )
    return list(result.all())


@router.get(
    "/llm",
    response_model=list[ProviderOut],
    summary="获取当前用户的 LLM 配置",
)
async def get_llm_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    rows = await _list_user_providers(db, current_user.id)
    return rows  # type: ignore[return-value]


@router.put(
    "/llm",
    response_model=list[ProviderOut],
    summary="整表替换当前用户的 LLM 配置",
)
async def put_llm_providers(
    payload: LlmProvidersUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    """删除该用户原有配置后按提交的列表重新写入。

    仅允许一个 is_active：若前端未正确标记，则保底把第一条设为 active。
    """
    await db.execute(delete(LlmProvider).where(LlmProvider.user_id == current_user.id))

    has_active = any(p.is_active for p in payload.providers)
    for idx, p in enumerate(payload.providers):
        is_active = p.is_active if has_active else idx == 0
        db.add(
            LlmProvider(
                user_id=current_user.id,
                platform=p.platform,
                name=p.name,
                base_url=p.base_url,
                api_key=p.api_key,
                default_model=p.default_model,
                supports_thinking=p.supports_thinking,
                is_active=is_active,
            )
        )
    await db.commit()

    rows = await _list_user_providers(db, current_user.id)
    return rows  # type: ignore[return-value]
