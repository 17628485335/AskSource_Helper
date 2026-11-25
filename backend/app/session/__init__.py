"""Session 会话模块：会话与消息落库（MySQL）+ 查询接口 + 对话历史函数"""

from .models import ChatMessage, ChatSession
from .router import router
from .schemas import (
    HistoryMessage,
    MessageCreate,
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionPage,
    SessionUpdate,
)
from .service import (
    DEFAULT_HISTORY_LIMIT,
    append_message,
    count_messages,
    create_session,
    delete_session,
    get_recent_session,
    get_session,
    list_sessions,
    load_history,
    load_messages,
    to_lc_messages,
    update_session,
)

__all__ = [
    # ORM 模型
    "ChatSession",
    "ChatMessage",
    # 请求 / 响应模型
    "SessionCreate",
    "SessionUpdate",
    "SessionOut",
    "SessionPage",
    "MessageCreate",
    "MessageOut",
    "HistoryMessage",
    # 服务函数
    "DEFAULT_HISTORY_LIMIT",
    "create_session",
    "get_session",
    "list_sessions",
    "update_session",
    "delete_session",
    "append_message",
    "load_messages",
    "load_history",
    "count_messages",
    "to_lc_messages",
    "get_recent_session",
    "router",
]
