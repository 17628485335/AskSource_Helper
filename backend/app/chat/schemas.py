"""对话接口的 Pydantic 请求模型"""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """POST /chat 请求体。

    不传 session_id 时后端自动新建会话，并在 SSE 的 meta 事件里把 id 回给前端；
    不传 platform / model 时取管理员 is_active 的那一行。
    """

    message: str = Field(min_length=1, max_length=8000)
    session_id: int | None = Field(default=None, ge=1)
    platform: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    thinking: bool | None = Field(
        default=None,
        description="深度思考档位；仅当该模型支持时生效，留空按快速发",
    )
    workspace_id: int | None = Field(
        default=None, ge=1, description="仅新建会话时生效；留空归入默认工作区"
    )
    regenerate: bool = Field(
        default=False,
        description="编辑末条提问后重新生成：先删除本轮（末条 user 及其后续）再追加新提问",
    )
    agent_key: str | None = Field(
        default=None,
        max_length=64,
        description="agents 表里的稳定标识；留空走默认 chat，配置缺失时回退代码默认值",
    )

    @field_validator("platform", "model", "agent_key", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """模型定位字段去空格：库里存有旧脏数据时，前端原样回传的名字也能命中池里的键"""
        return value.strip() if isinstance(value, str) else value
