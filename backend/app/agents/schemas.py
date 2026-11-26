"""Agent 管理接口的 Pydantic 请求 / 响应模型"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

AGENT_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class AgentCreate(BaseModel):
    """新建 agent；system_prompt 非空时会同时生成 version=1"""

    agent_key: str = Field(pattern=AGENT_KEY_PATTERN, description="稳定标识，如 chat / planner")
    name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=255)
    platform: str = Field(default="", max_length=64, description="留空沿用请求里的平台")
    model: str = Field(default="", max_length=128, description="留空沿用请求里的模型")
    thinking: bool = False
    tool_names: list[str] | None = Field(
        default=None,
        description="工具白名单；null=全部工具，[]=禁用所有工具",
    )
    system_prompt: str = Field(default="", max_length=20000)


class AgentUpdate(BaseModel):
    """PATCH 语义：只改显式传来的字段"""

    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    thinking: bool | None = None
    tool_names: list[str] | None = Field(default=None, description="null=全部工具，[]=禁用所有工具")
    active_prompt_version: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class AgentOut(BaseModel):
    """agent 定义；提示词正文在 /agents/{id}/prompts 里读"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_key: str
    name: str
    description: str
    platform: str
    model: str
    thinking: bool
    tool_names: list[str] | None
    active_prompt_version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentPromptCreate(BaseModel):
    """新增提示词版本；版本自动递增，activate=True 时同步切到新版本"""

    system_prompt: str = Field(min_length=1, max_length=20000)
    note: str = Field(default="", max_length=255)
    activate: bool = True


class AgentPromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    version: int
    system_prompt: str
    note: str
    created_at: datetime
