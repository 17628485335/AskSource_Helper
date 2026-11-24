"""LLM 平台配置与「深度思考」参数适配

设计要点：把各平台深度思考的参数差异做成一张数据表 THINKING，
切换模型 / 开关深度思考时查表拼参数，再交给 langchain 的 create_agent 使用。
配置优先从环境变量 / backend/.env 读取，风格与 auth/config.py 保持一致。
"""

from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    """单个 LLM 平台的可选覆盖项（base_url / api_key / 默认模型）

    留空则回退到内置默认（base_url 见 PROVIDER_BASE_URLS）。
    """

    base_url: str = ""
    api_key: str = ""
    default_model: str = ""


class ProviderOption(BaseModel):
    """下拉框选项：模型提供商（含用于前端预填的 base_url）"""

    value: str
    label: str
    base_url: str = ""


# 三个平台的默认 OpenAI 兼容 base_url（可被 .env 中的 <平台>__BASE_URL 覆盖）
PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


# 「模型提供商」下拉框选项，前端拉取后渲染（base_url 取内置默认，接口会按 env 覆盖后返回）
MODEL_PROVIDERS: list[ProviderOption] = [
    ProviderOption(value="bailian", label="阿里百炼", base_url=PROVIDER_BASE_URLS["bailian"]),
    ProviderOption(value="deepseek", label="DeepSeek", base_url=PROVIDER_BASE_URLS["deepseek"]),
    ProviderOption(value="siliconflow", label="硅基流动", base_url=PROVIDER_BASE_URLS["siliconflow"]),
]


def resolve_base_url(platform: str) -> str | None:
    """取平台生效的 base_url：优先 .env 覆盖值，其次内置默认；未知平台返回 None。"""
    if platform not in PROVIDER_BASE_URLS:
        return None
    settings = get_llm_settings()
    conf = getattr(settings, platform, None)
    if conf and conf.base_url:
        return conf.base_url
    return PROVIDER_BASE_URLS[platform]


class LLMSettings(BaseSettings):
    """LLM 平台集合配置；未配置的平台为 None"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 各家 base_url / api_key / 默认模型，按需通过 .env 覆盖
    deepseek: ProviderConfig | None = None
    siliconflow: ProviderConfig | None = None
    bailian: ProviderConfig | None = None


# (平台, 模型) -> 深度思考开启时要合并到 init_chat_model 的请求参数
# 差异全靠这张表声明，新增模型只加一行，不改逻辑
THINKING: dict[tuple[str, str], dict[str, Any]] = {
    ("deepseek", "deepseek-chat"): {"model": "deepseek-reasoner"},  # 靠换模型开启
    ("siliconflow", "Qwen3-32B"): {"extra_body": {"enable_thinking": True}},
    ("bailian", "qwen-plus"): {"extra_body": {"enable_thinking": True}, "streaming": True},
}


@lru_cache
def get_llm_settings() -> LLMSettings:
    """带缓存的 LLM 配置单例"""
    return LLMSettings()


def build_model(platform: str, model: str, thinking: bool):
    """按平台 + 模型构建 langchain chat 模型；开启深度思考时查表自动带对应参数。

    base_url 由 resolve_base_url 得出（env 优先，否则内置默认）；api_key / 默认模型也从 env 覆盖。
    返回的对象可直接传给 langchain.agents.create_agent(model=..., tools=...)。
    """
    from langchain.chat_models import init_chat_model

    base_url = resolve_base_url(platform)
    if not base_url:
        raise ValueError(f"未知的平台: {platform}")

    settings = get_llm_settings()
    conf = getattr(settings, platform, None)

    kwargs: dict[str, Any] = {
        "model": model or (conf.default_model if conf else ""),
        "model_provider": "openai",
        "base_url": base_url,
        "api_key": conf.api_key if conf else "",
    }
    if thinking:
        kwargs.update(THINKING.get((platform, kwargs["model"]), {}))
    return init_chat_model(**kwargs)


async def test_provider_connection(
    base_url: str, api_key: str, default_model: str = ""
) -> dict[str, Any]:
    """探测 LLM 提供商的连通性与密钥有效性。

    走 OpenAI 兼容的 ``GET {base_url}/models``：返回 200 即说明 endpoint 可达且密钥被接受。
    若填写了 default_model，额外校验其是否在可用模型列表中。
    不依赖已保存配置，直接用表单草稿值探测，便于保存前验证。
    """
    import httpx

    base = (base_url or "").rstrip("/")
    key = (api_key or "").strip()
    if not base:
        return {"ok": False, "detail": "未填写 API 端点（base_url）", "model_count": None}
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "detail": "API 端点需以 http:// 或 https:// 开头", "model_count": None}
    if not key:
        return {"ok": False, "detail": "未填写 API 密钥", "model_count": None}

    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return {"ok": False, "detail": "连接超时（10s），请检查端点地址或网络", "model_count": None}
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"无法连接到端点：{exc.__class__.__name__}", "model_count": None}

    if resp.status_code in (401, 403):
        return {"ok": False, "detail": f"密钥无效或被拒绝（HTTP {resp.status_code}）", "model_count": None}
    if resp.status_code >= 400:
        snippet = (resp.text or "").strip().replace("\n", " ")[:160]
        return {
            "ok": False,
            "detail": f"端点返回 HTTP {resp.status_code}：{snippet or '无响应体'}",
            "model_count": None,
        }

    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "detail": "端点返回的不是合法 JSON，可能不是 OpenAI 兼容地址", "model_count": None}

    models = data.get("data") if isinstance(data, dict) else None
    model_ids = {m.get("id") for m in models if isinstance(m, dict)} if isinstance(models, list) else set()
    count = len(model_ids)

    model = (default_model or "").strip()
    if model and model_ids and model not in model_ids:
        return {
            "ok": False,
            "detail": f"连接成功，但模型「{model}」不在可用列表中", 
            "model_count": count,
        }
    return {"ok": True, "detail": "连接成功，密钥有效", "model_count": count}
