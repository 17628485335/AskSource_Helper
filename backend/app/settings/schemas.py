"""设置模块的 Pydantic 请求 / 响应模型"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CONTEXT_SIZE = 200000


class ProviderWrite(BaseModel):
    """写入单个 LLM 提供商（PUT 请求体元素）"""

    platform: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    default_model: str = Field(default="", max_length=128)
    context_size: int = Field(
        default=DEFAULT_CONTEXT_SIZE,
        ge=1024,
        le=2_000_000,
        description="模型上下文窗口（token），用于裁剪对话历史",
    )
    supports_thinking: bool = False
    is_active: bool = False

    @field_validator("platform", "name", "base_url", "api_key", "default_model", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """写入端就把首尾空格洗掉。

        ChatManager 建池用的是 strip 后的 (平台, 模型)，而 /settings/models 返回的是列原值；
        库里存了「 qwen-plus 」时，下拉里能选到它，传回 /chat 就对不上池里的键，
        表现为「未接入模型」。在唯一写入口收紧，比在每个读取端各自补 strip 可靠。
        """
        return value.strip() if isinstance(value, str) else value


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
    context_size: int
    supports_thinking: bool
    is_active: bool


class ToolOut(BaseModel):
    """GET /settings/tools 响应元素：中文展示名 + 工具名 + lucide 图标名"""

    name: str
    label: str
    icon: str = ""


class ChatModelOption(BaseModel):
    """GET /settings/models 响应元素：给对话框选模型用，不携带任何密钥字段"""

    platform: str
    platform_label: str
    model: str
    name: str = ""
    context_size: int = DEFAULT_CONTEXT_SIZE
    supports_thinking: bool = Field(
        default=False,
        description="该行是否有深度档位：前端据此决定是否展示 快速/深度 选择",
    )
    is_active: bool = False
    available: bool = Field(
        default=True,
        description="该行是否真的建进了模型池：false 表示配置还在表里但构建失败，前端应置灰",
    )
    unavailable_reason: str = Field(
        default="",
        description="available=false 时的原因（取自模型池的 errors），供前端提示管理员",
    )


class ProviderTestRequest(BaseModel):
    """POST /settings/llm/test 请求体：用表单草稿值探测，无需先保存（仅管理员）"""

    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    default_model: str = Field(default="", max_length=128)


class ProviderTestResult(BaseModel):
    """连通性测试结果"""

    ok: bool
    detail: str
    model_count: int | None = None
