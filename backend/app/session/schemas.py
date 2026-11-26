"""会话模块的 Pydantic 请求 / 响应模型"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant", "system", "tools"]
SessionStatus = Literal["active", "archived"]


class SessionCreate(BaseModel):
    """POST /sessions 请求体：新建会话，全部字段可选"""

    title: str = Field(default="", max_length=255)
    platform: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    thinking: bool = False
    workspace_id: int | None = Field(default=None, ge=1)


class SessionUpdate(BaseModel):
    """PATCH /sessions/{id} 请求体：改名或归档，未传的字段不动"""

    title: str | None = Field(default=None, max_length=255)
    status: SessionStatus | None = None


class MessageCreate(BaseModel):
    """POST /sessions/{id}/messages 请求体：追加一条消息"""

    role: MessageRole
    content: str = Field(min_length=1)
    tool_name: str = Field(default="", max_length=128)
    tokens: int = Field(default=0, ge=0)


class ToolCallOut(BaseModel):
    """一次工具调用的结构化记录（从 chat_tool_calls 表读出）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    message_id: int
    seq: int
    tool_name: str
    call_id: str
    created_at: datetime
    turn_id: int | None = None
    segment_id: int | None = None
    input_json: dict[str, Any] | None = None
    result_text: str = ""
    preview: str = ""
    duration_ms: int | None = None
    citations_json: list[dict[str, Any]] | None = None


class MessageOut(BaseModel):
    """消息响应元素"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    tool_name: str
    tokens: int
    created_at: datetime
    turn_id: int | None = None
    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class SessionOut(BaseModel):
    """会话响应元素；message_count 由服务层回填（ORM 上同名字段为计数缓存）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    workspace_id: int | None
    platform: str
    model: str
    thinking: bool
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionPage(BaseModel):
    """GET /sessions 响应：列表 + 分页游标，便于前端加载更多"""

    items: list[SessionOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class HistoryMessage(BaseModel):
    """对话历史响应元素：按时间正序，供前端渲染或拼 prompt"""

    role: str
    content: str
    tool_name: str = ""
    turn_id: int | None = None
