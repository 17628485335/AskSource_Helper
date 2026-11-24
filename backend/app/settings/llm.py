"""LLM 平台配置与「深度思考」参数适配

设计要点：把各平台深度思考的参数差异做成一张数据表 THINKING，
切换模型 / 开关深度思考时查表拼参数，再交给 langchain 的 create_agent 使用。
配置优先从环境变量 / backend/.env 读取，风格与 auth/config.py 保持一致。
"""

from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI
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
        # 嵌套字段靠双下划线映射（如 DEEPSEEK__API_KEY -> deepseek.api_key），
        # 不设这个分隔符时 .env 里的平台配置会被 extra="ignore" 静默丢掉。
        env_nested_delimiter="__",
        extra="ignore",
    )

    # 各家 base_url / api_key / 默认模型，按需通过 .env 覆盖
    deepseek: ProviderConfig | None = None
    siliconflow: ProviderConfig | None = None
    bailian: ProviderConfig | None = None


# 平台 -> 深度思考开关时要合并到 init_chat_model 的请求参数，分 on / off 两套：
# on 对应 thinking=True；off 对应 thinking=False（前端选「快速」），用于显式关闭默认开启推理的模型。
# 只按平台查表，不区分具体模型：同平台下思考开关的参数写法一致。
# 新增平台只加一行，不改逻辑
THINKING: dict[str, dict[str, dict[str, Any]]] = {
    "deepseek": {"on": {"model": "deepseek-reasoner"}},  # 靠换模型开启；关闭即用原模型，无需额外参数
    "siliconflow": {
        "on": {"extra_body": {"enable_thinking": True}},
        # 混合思考模型默认开思考，快速模式必须显式关。实测（11-25）Xing4.0-29B 支持本参数：
        # 经 SDK 平铺到 JSON 顶层后思考帧归零；注意 extra_body 是客户端概念，
        # 用裸 httpx 对照时必须把键放顶层，直接发嵌套的 extra_body 会被服务端静默忽略。
        "off": {"extra_body": {"enable_thinking": False}},
    },
    "bailian": {
        "on": {"extra_body": {"enable_thinking": True}, "streaming": True},
        "off": {"extra_body": {"enable_thinking": False}},
    },
}


@lru_cache
def get_llm_settings() -> LLMSettings:
    """带缓存的 LLM 配置单例"""
    return LLMSettings()


def _reasoning_delta(chunk: Any) -> str:
    """从一条流式 chunk 里取思考增量；取不到就返回空串。

    _astream 传进来的已经是 dict（chunk.model_dump()），所以逐层都要容错：
    usage 帧、choices 为空的帧、甚至 delta 里没有该字段的普通模型，都是正常情况。
    """
    if not isinstance(chunk, dict):
        return ""
    choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta")
    value = delta.get("reasoning_content") if isinstance(delta, dict) else None
    return value if isinstance(value, str) else ""


class ReasoningChatOpenAI(ChatOpenAI):
    """把上游 delta 里的 reasoning_content 接住的 ChatOpenAI，其余行为与父类一致。

    为什么要自己补：langchain-openai 在模块注释里写明 reasoning_content 这类推理字段
    「are not extracted」，不提取也不进 additional_kwargs，官方建议改用平台专用子类
    （如 ChatDeepSeek）。不接的话实测深度档 82 个 delta 里有 79 个变成空 content ——
    前端看不到任何思考过程，快速档和深度档的可见输出长得一模一样，用户只会认为档位没生效。

    思考内容只挂在 additional_kwargs 里随流转发给前端，不进正文、不落库。
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: Any,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> Any:
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation is None:
            return None
        reasoning = _reasoning_delta(chunk)
        if reasoning:
            generation.message.additional_kwargs["reasoning_content"] = reasoning
        return generation


def build_model(
    platform: str,
    model: str,
    thinking: bool,
    *,
    api_key: str = "",
    base_url: str = "",
):
    """按平台 + 模型构建 chat 模型；查表按 thinking 布尔合并 on / off 对应参数。

    thinking=True 合并表里的 on（深度思考）；thinking=False 合并 off（如 enable_thinking=false，
    显式关闭 Qwen3 这类默认开启推理的模型）；表里没有 off 则保持默认行为。
    base_url 由 resolve_base_url 得出（env 优先，否则内置默认）；api_key / 默认模型也从 env 覆盖。
    api_key / base_url 传入非空值时优先级最高，用于把数据库里用户自配的密钥接进来。
    返回的对象可直接传给 langchain.agents.create_agent(model=..., tools=...)。

    这里不走 init_chat_model 而是直接构造 ReasoningChatOpenAI：这几个平台本来就都是
    OpenAI 兼容端点，init_chat_model(model_provider="openai") 出来的就是 ChatOpenAI，
    少了这层间接才能换成自己的子类；传参名（model / base_url / api_key / extra_body /
    streaming）都是父类字段，_get_request_payload 的输出与原写法逐字一致。
    """
    resolved_base = base_url or resolve_base_url(platform)
    if not resolved_base:
        raise ValueError(f"未知的平台: {platform}")

    settings = get_llm_settings()
    conf = getattr(settings, platform, None)

    kwargs: dict[str, Any] = {
        "model": model or (conf.default_model if conf else ""),
        "base_url": resolved_base,
        "api_key": api_key or (conf.api_key if conf else ""),
    }
    mapping = THINKING.get(platform, {})
    # 两个分支都要容错：表里没配这个平台时 mapping 为空 dict，
    # 用 mapping["on"] 会直接 KeyError；此时保持模型默认行为（与无映射时一致）。
    kwargs.update(mapping.get("on", {}) if thinking else mapping.get("off", {}))
    return ReasoningChatOpenAI(**kwargs)


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
