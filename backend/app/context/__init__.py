"""上下文段模块：agent 绑定 / agent 文档 / 用户文档 / 能力快照 / 对话历史组装。

router 不由包初始化导出：app.context 会被 chat / session 等模块导入，
在 __init__ 里加载 router 会把 chat.chat_manager 一起拖进来形成导入环。
路由统一由 app.main 显式从 .context.router 挂载。
"""

from .assembler import build_skills_snapshot
from .generator import generate_context_content
from .history import load_history, load_history_with_tools, wrap_history
from .history_compactor import compact_history
from .models import AgentContextBinding, AgentContextDoc, AgentMemory, UserContextDoc
from .schemas import (
    AgentContextBindingCreate,
    AgentContextBindingOut,
    AgentContextBindingUpdate,
    AgentContextDocCreate,
    AgentContextDocOut,
    AgentContextDocUpdate,
    UserContextDocCreate,
    UserContextDocOut,
    UserContextDocUpdate,
)
from .token_counter import count_context_tokens, estimate_message_tokens, estimate_text_tokens
from .usage import get_context_usage
from .service import (
    ContextConflict,
    ContextNotFound,
    content_hash,
    create_agent_doc,
    create_binding,
    create_user_doc,
    delete_agent_doc,
    delete_binding,
    delete_user_doc,
    find_agent_doc,
    find_user_doc,
    list_agent_docs,
    list_bindings,
    list_user_docs,
    update_agent_doc,
    update_binding,
    update_user_doc,
)

__all__ = [
    "AgentContextBinding",
    "AgentContextDoc",
    "UserContextDoc",
    "build_skills_snapshot",
    "compact_history",
    "load_history",
    "load_history_with_tools",
    "wrap_history",
    "generate_context_content",
    "get_context_usage",
    "AgentContextBindingCreate",
    "AgentContextBindingOut",
    "AgentContextBindingUpdate",
    "AgentContextDocCreate",
    "AgentContextDocOut",
    "AgentContextDocUpdate",
    "UserContextDocCreate",
    "UserContextDocOut",
    "UserContextDocUpdate",
    "ContextConflict",
    "ContextNotFound",
    "content_hash",
    "list_bindings",
    "create_binding",
    "update_binding",
    "delete_binding",
    "list_agent_docs",
    "create_agent_doc",
    "update_agent_doc",
    "delete_agent_doc",
    "find_agent_doc",
    "list_user_docs",
    "create_user_doc",
    "update_user_doc",
    "delete_user_doc",
    "find_user_doc",
    "count_context_tokens",
    "estimate_message_tokens",
    "estimate_text_tokens",
]
