"""Settings 设置相关模块包。

router 由 app.main 从 .settings.router 显式挂载；包初始化只导出配置与模型构造，
避免把 router 对 app.chat 的延迟依赖带进其它模块的导入路径。
"""

from .llm import (
    MODEL_PROVIDERS,
    THINKING,
    LLMSettings,
    ProviderConfig,
    ProviderOption,
    build_model,
    get_llm_settings,
)

__all__ = [
    "MODEL_PROVIDERS",
    "THINKING",
    "LLMSettings",
    "ProviderConfig",
    "ProviderOption",
    "build_model",
    "get_llm_settings",
]
