"""设置相关路由

- /settings/model-providers：模型提供商下拉选项（静态）
- /settings/models：对话时可选的模型列表（登录即可读，不含密钥）
- /settings/llm：模型密钥配置的读写（仅管理员）

llm_providers 不再是「每个用户一份」：/chat 解析配置时不按 user_id 过滤，
所以这张表全库只有一份生效配置，写入端必须收紧到管理员，否则任何登录用户
保存设置页都能顶掉管理员的密钥、影响所有人的对话。user_id 列仅作为「谁配的」审计标记。

一行 = 一个可对话的模型，所以同平台可以插多行（多个模型）；保存后需要重建
ChatManager 的模型池，否则新接入的模型要重启服务才进得了 /chat。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.database import get_db
from auth.deps import get_current_admin, get_current_user
from auth.models import User

from .llm import MODEL_PROVIDERS, ProviderOption, resolve_base_url, test_provider_connection
from .models import LlmProvider
from .schemas import (
    ChatModelOption,
    LlmProvidersUpdate,
    ProviderOut,
    ProviderTestRequest,
    ProviderTestResult,
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


async def _list_providers(db: AsyncSession) -> list[LlmProvider]:
    """取全局配置行（不按 user 过滤）：生效的那条排最前，同状态按接入先后"""
    result = await db.scalars(
        select(LlmProvider).order_by(LlmProvider.is_active.desc(), LlmProvider.id)
    )
    return list(result.all())


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
    for row in await _list_providers(db):
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
    rows = await _list_providers(db)
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
    """删除表内全部配置后按提交的列表重新写入。

    注意是「全表」而不是「当前用户的行」：配置已经全局生效，留着别人的行会让
    /chat 的回落结果不可预测。仅允许一个 is_active：前端未标记时保底把第一条设为 active。
    同 (平台, 模型) 只保留第一条：重复行会让下拉出现重复项，/chat 命中哪一条也不确定。
    保存后立即重建模型池（ChatManager.reload），新接入的模型无需重启即可用。
    """
    await db.execute(delete(LlmProvider))

    has_active = any(p.is_active for p in payload.providers)
    seen: set[tuple[str, str]] = set()
    inserted = 0
    for p in payload.providers:
        model = (p.default_model or "").strip()
        if model and (p.platform, model) in seen:
            continue
        if model:
            seen.add((p.platform, model))
        is_active = p.is_active if has_active else inserted == 0
        db.add(
            LlmProvider(
                user_id=current_user.id,
                platform=p.platform,
                name=p.name,
                base_url=p.base_url,
                api_key=p.api_key,
                # 存 strip 后的值：ProviderWrite 已经洗过，这里再保一道，让表里的键
                # 与 ChatManager 建池用的键一致
                default_model=model,
                supports_thinking=p.supports_thinking,
                is_active=is_active,
            )
        )
        inserted += 1
    await db.commit()

    # 延迟导入：app.settings.__init__ 会 import 本模块，而 chat_manager 反过来
    # 依赖 app.settings —— 放到顶层会形成循环。
    from app.chat import ChatManager

    # 正在流式回答的请求继续用旧实例，新请求从重建后的池里挑
    await ChatManager.reload(db)

    rows = await _list_providers(db)
    return rows  # type: ignore[return-value]
