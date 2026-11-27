"""设置相关路由

- /settings/model-providers：模型提供商下拉选项（静态）
- /settings/models：对话时可选的模型列表（登录即可读，不含密钥）
- /settings/llm：模型密钥配置的读写（仅管理员）
- /settings/tools：当前真正挂进模型池的工具列表（登录即可读）

llm_providers 不再是「每个用户一份」：/chat 解析配置时不按 user_id 过滤，
所以这张表全库只有一份生效配置，写入端必须收紧到管理员，否则任何登录用户
保存设置页都能顶掉管理员的密钥、影响所有人的对话。user_id 列仅作为「谁配的」审计标记。

一行 = 一个可对话的模型，所以同平台可以插多行（多个模型）；保存后需要重建
ChatManager 的模型池，否则新接入的模型要重启服务才进得了 /chat。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_admin, get_current_user
from auth.models import User

from app.graph import get_tool_spec

from . import service as settings_service
from .llm import MODEL_PROVIDERS, ProviderOption, resolve_base_url, test_provider_connection
from .schemas import (
    ChatModelOption,
    LlmProvidersUpdate,
    ProviderOut,
    ProviderTestRequest,
    ProviderTestResult,
    ToolOut,
)

router = APIRouter(prefix="/settings", tags=["settings"])

# 平台 value -> 中文名，给不含密钥的模型列表用
PLATFORM_LABELS = {opt.value: opt.label for opt in MODEL_PROVIDERS}


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


@router.get(
    "/tools",
    response_model=list[ToolOut],
    summary="当前支持的工具列表（登录即可读）",
)
async def list_current_tools(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ToolOut]:
    """返回真正挂进模型池的工具，而不是注册表里所有声明。

    池在 build() 时已经过滤掉前置条件不满足的工具（如未配置密钥的搜索），
    侧边栏据此展示「当前支持」；取不到池时返回空列表，把错误留给 /chat。
    """
    from app.chat import ChatManager

    try:
        pool = await ChatManager.get(db)
    except Exception:
        return []

    result: list[ToolOut] = []
    for tool in pool.tools:
        name = getattr(tool, "name", "")
        if not name:
            continue
        spec = get_tool_spec(name)
        result.append(
            ToolOut(
                name=name,
                label=spec.label if spec else name,
                icon=spec.icon if spec else "",
            )
        )
    return result


@router.post(
    "/llm/test",
    response_model=ProviderTestResult,
    summary="测试 LLM 提供商连通性与密钥有效性",
)
async def test_llm_provider(
    payload: ProviderTestRequest,
    current_user: User = Depends(get_current_admin),
) -> ProviderTestResult:
    """用提交的 base_url + api_key 探测一次（仅管理员，避免被当作开放代理）。"""
    result = await test_provider_connection(
        payload.base_url, payload.api_key, payload.default_model
    )
    return ProviderTestResult(**result)





@router.get(
    "/models",
    response_model=list[ChatModelOption],
    summary="获取对话可选的模型列表（不含密钥）",
)
async def list_chat_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatModelOption]:
    """登录即可读，专给对话框的模型下拉用。

    管理员在 llm_providers 里每接入一行（平台 + 默认模型）就是一个可选项，
    is_active 那条为默认；响应里没有 base_url / api_key，所以普通用户拿不到密钥。
    supports_thinking 同步告知前端该模型有没有深度档位（决定 快速/深度 选择是否展示）。
    没填默认模型的行没意义（/chat 也会拒），直接不返回。

    available 拿常驻池比对得出：这一栏读的是表，能不能聊取决于池，一行构建失败（密
    钥失效、平台不认参数）时它仍然在表里。不标注就会出现「下拉里选得到、一发就报
    未接入」；取不到池时一律当成可用（至少别让模型列表先 500）。
    """
    # 延迟导入：app.settings.__init__ 会 import 本模块，而 chat_manager 反过来
    # 依赖 app.settings —— 放到顶层会形成循环。
    from app.chat import ChatManager

    try:
        pool = await ChatManager.get(db)
    except Exception:  # 库抖动 / 预热失败：列表照旧返回，把报错留给 /chat
        pool = None

    options: list[ChatModelOption] = []
    for row in await settings_service.list_providers(db):
        model = (row.default_model or "").strip()
        if not model:
            continue
        platform = (row.platform or "").strip()
        # 输出也 strip：库里可能存着历史脏数据，不洗会把同一个 bug 原样透给前端
        ok = pool is None or pool.has(platform, model)
        options.append(
            ChatModelOption(
                platform=platform,
                platform_label=PLATFORM_LABELS.get(platform, platform),
                model=model,
                name=row.name,
                context_size=row.context_size,
                supports_thinking=row.supports_thinking,
                is_active=row.is_active,
                available=ok,
                unavailable_reason="" if ok else pool.unavailable_reason(platform, model),  # type: ignore[union-attr]
            )
        )
    return options


@router.get(
    "/llm",
    response_model=list[ProviderOut],
    summary="获取全局 LLM 配置（仅管理员）",
)
async def get_llm_providers(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    """含 api_key 明文，所以只对管理员开放；普通用户走 /settings/models"""
    rows = await settings_service.list_providers(db)
    return rows  # type: ignore[return-value]


@router.put(
    "/llm",
    response_model=list[ProviderOut],
    summary="整表替换全局 LLM 配置（仅管理员）",
)
async def put_llm_providers(
    payload: LlmProvidersUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    """整表替换并重建模型池；写库与去重/active 规则由 service 负责。"""
    rows = await settings_service.replace_llm_providers(
        db, user_id=current_user.id, providers=payload.providers
    )
    return rows  # type: ignore[return-value]
