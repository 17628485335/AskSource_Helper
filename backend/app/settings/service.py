"""LLM 配置读写：整表替换与查询的业务规则。

router 只负责权限校验、请求/响应模型与异常转 HTTP；写库规则在这里。
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LlmProvider
from .schemas import ProviderWrite


async def list_providers(db: AsyncSession) -> list[LlmProvider]:
    """取全局配置行（不按 user 过滤）：生效的那条排最前，同状态按接入先后。"""
    result = await db.scalars(
        select(LlmProvider).order_by(LlmProvider.is_active.desc(), LlmProvider.id)
    )
    return list(result.all())


async def replace_llm_providers(
    db: AsyncSession,
    *,
    user_id: int,
    providers: list[ProviderWrite],
) -> list[LlmProvider]:
    """删除表内全部配置后按提交列表重新写入，并重建模型池。

    是全表而不是当前用户的行：配置已全局生效，留着别人的行会让 /chat 的回落
    结果不可预测。仅允许一个 is_active；前端未标记时保底把第一条设为 active。
    同 (平台, 模型) 只保留第一条，避免下拉出现重复项、/chat 命中不确定。
    """
    await db.execute(delete(LlmProvider))

    has_active = any(p.is_active for p in providers)
    seen: set[tuple[str, str]] = set()
    inserted = 0
    for p in providers:
        model = (p.default_model or "").strip()
        if model and (p.platform, model) in seen:
            continue
        if model:
            seen.add((p.platform, model))
        db.add(
            LlmProvider(
                user_id=user_id,
                platform=p.platform,
                name=p.name,
                base_url=p.base_url,
                api_key=p.api_key,
                default_model=model,
                context_size=p.context_size,
                supports_thinking=p.supports_thinking,
                is_active=p.is_active if has_active else inserted == 0,
            )
        )
        inserted += 1
    await db.commit()

    # 延迟导入：chat_manager 依赖 app.settings，放到顶层会形成循环。
    from app.chat import ChatManager

    # 正在流式回答的请求继续用旧实例，新请求从重建后的池里挑
    await ChatManager.reload(db)
    return await list_providers(db)
