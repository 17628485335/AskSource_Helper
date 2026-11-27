"""Session 会话模块：会话与消息落库（MySQL）+ 查询接口。

router 由 app.main 从 .session.router 显式挂载；包初始化只导出数据层与模型，
避免把 router 的依赖链带进其它模块的导入路径。
"""

from .models import ChatMessage, ChatSession
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
    create_session,
    get_summary,
    load_latest_usage_turn,
    load_turn_usages,
    mark_summarized,
    record_turn_usage,
    delete_session,
    get_session,
    list_sessions,
    load_unsummarized_messages,
    load_messages,
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
    "get_summary",
    "load_latest_usage_turn",
    "load_turn_usages",
    "mark_summarized",
    "record_turn_usage",
    "load_unsummarized_messages",
    "load_messages",
]
