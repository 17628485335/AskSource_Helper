"""设置模块的 Pydantic 请求 / 响应模型"""

from pydantic import BaseModel, ConfigDict, Field


class ProviderWrite(BaseModel):
    """写入单个 LLM 提供商（PUT 请求体元素）"""

    platform: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    default_model: str = Field(default="", max_length=128)
    supports_thinking: bool = False
    is_active: bool = False


class LlmProvidersUpdate(BaseModel):
    """PUT /settings/llm 请求体：整表替换当前用户的提供商列表"""

    providers: list[ProviderWrite] = Field(default_factory=list)


class ProviderOut(BaseModel):
    """GET /settings/llm 响应元素"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    name: str
    base_url: str
    api_key: str
    default_model: str
    supports_thinking: bool
    is_active: bool


class ProviderTestRequest(BaseModel):
    """POST /settings/llm/test 请求体：用表单草稿值探测，无需先保存"""

    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    default_model: str = Field(default="", max_length=128)


class ProviderTestResult(BaseModel):
    """连通性测试结果"""

    ok: bool
    detail: str
    model_count: int | None = None
