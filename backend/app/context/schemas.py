"""上下文段的 Pydantic 请求 / 响应模型"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTEXT_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
Resolver = Literal["agent_doc", "user_doc", "generated", "memory", "none"]
TrustLevel = Literal["anchor", "policy", "data", "generated"]


class AgentContextBindingCreate(BaseModel):
    key: str = Field(pattern=CONTEXT_KEY_PATTERN, description="soul / user_profile ...")
    title: str = Field(default="", max_length=128)
    resolver: Resolver = "none"
    ref_key: str = Field(default="", max_length=64)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    max_tokens: int = Field(default=1000, ge=1, le=32000)
    trust_level: TrustLevel = "data"
    trust_hint: str = Field(default="", max_length=128)


class AgentContextBindingUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    resolver: Resolver | None = None
    ref_key: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)
    trust_level: TrustLevel | None = None
    trust_hint: str | None = Field(default=None, max_length=128)


class AgentContextBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    key: str
    title: str
    resolver: str
    ref_key: str
    enabled: bool
    priority: int
    max_tokens: int
    trust_level: str
    trust_hint: str
    created_at: datetime
    updated_at: datetime


class AgentContextDocCreate(BaseModel):
    """agent_id 不传表示全局共享文档"""

    agent_id: int | None = Field(default=None, ge=1)
    key: str = Field(pattern=CONTEXT_KEY_PATTERN)
    title: str = Field(default="", max_length=128)
    content: str = Field(default="", max_length=20000)


class AgentContextDocUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    content: str | None = Field(default=None, max_length=20000)


class AgentContextDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int | None
    key: str
    title: str
    content: str
    version_hash: str
    created_at: datetime
    updated_at: datetime


class UserContextDocCreate(BaseModel):
    key: str = Field(pattern=CONTEXT_KEY_PATTERN)
    title: str = Field(default="", max_length=128)
    content: str = Field(default="", max_length=20000)


class UserContextDocUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    content: str | None = Field(default=None, max_length=20000)


class UserContextDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    key: str
    title: str
    content: str
    version_hash: str
    created_at: datetime
    updated_at: datetime


class ContextGenerateRequest(BaseModel):
    kind: Literal["soul", "identity", "agents_guide", "user_profile"]
    agent_id: int | None = Field(default=None, ge=1)
    current: str = Field(default="", max_length=20000)
    hint: str = Field(default="", max_length=1000)
    variant: int = Field(default=0, ge=0, le=100)


class ContextGenerateResponse(BaseModel):
    content: str


class SystemPromptComposeRequest(BaseModel):
    prompt: str = Field(max_length=20000)
    agent_id: int | None = Field(default=None, ge=1)
    tool_names: list[str] | None = None


class SystemPromptComposeResponse(BaseModel):
    content: str


class AgentMemoryCreate(BaseModel):
    content: str = Field(max_length=20000)


class AgentMemoryUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=20000)
    enabled: bool | None = None


class AgentMemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    content: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
