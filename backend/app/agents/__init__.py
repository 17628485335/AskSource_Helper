"""Agent 定义与提示词版本模块：ORM / 管理接口 / 请求解析服务"""

from .models import Agent, AgentPrompt
from .router import router
from .schemas import (
    AgentCreate,
    AgentOut,
    AgentPromptCreate,
    AgentPromptOut,
    AgentUpdate,
)
from .service import (
    AgentContext,
    AgentKeyExists,
    AgentNotFound,
    PromptNotFound,
    activate_prompt,
    create_agent,
    create_prompt,
    delete_agent,
    get_agent,
    get_agent_by_key,
    list_agents,
    list_prompts,
    resolve_agent,
    update_agent,
)

__all__ = [
    # ORM
    "Agent",
    "AgentPrompt",
    # 请求 / 响应
    "AgentCreate",
    "AgentUpdate",
    "AgentOut",
    "AgentPromptCreate",
    "AgentPromptOut",
    # 服务
    "AgentContext",
    "AgentNotFound",
    "AgentKeyExists",
    "PromptNotFound",
    "list_agents",
    "get_agent",
    "get_agent_by_key",
    "create_agent",
    "update_agent",
    "delete_agent",
    "list_prompts",
    "create_prompt",
    "activate_prompt",
    "resolve_agent",
    "router",
]
