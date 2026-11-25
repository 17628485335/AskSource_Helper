"""工作区模块的 Pydantic 请求 / 响应模型"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    """POST /workspaces 请求体"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)


class WorkspaceUpdate(BaseModel):
    """PATCH /workspaces/{id} 请求体：未传的字段不动"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class WorkspaceOut(BaseModel):
    """工作区响应元素；session_count 由服务层查询后回填"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    is_default: bool
    session_count: int = 0
    created_at: datetime
    updated_at: datetime
