"""Graph 模块包：工具注册表与流式事件协议（具体工具在 app/tools，会话在 app/session）

这里只放「图怎么拿到工具、图的事件怎么定义成前后端协议」的基础设施：
- tools.py：@register_tool 装饰器 + ToolSpec 注册表 + tool_is_available 可用性探测
- stream_protocol.py：流式事件协议，只放 ev_* 事件构造函数（消费逻辑在 ModelAgent.stream）
- 具体工具一律写在 app/tools/ 下（一个工具一个文件，导入该包即完成注册）
"""

from .stream_protocol import (
    ALL_EVENT_TYPES,
    EventType,
    ev_citations,
    ev_reasoning,
    ev_segment_start,
    ev_token,
    ev_tool_end,
    ev_tool_start,
)
from .tools import (
    ToolCategory,
    ToolSpec,
    clear_tools,
    get_tool,
    get_tool_spec,
    get_tools,
    list_tool_specs,
    register_tool,
    tool_is_available,
    unmet_requirements,
    unregister_tool,
)

__all__ = [
    "ALL_EVENT_TYPES",
    "EventType",
    "ev_token",
    "ev_reasoning",
    "ev_segment_start",
    "ev_tool_start",
    "ev_tool_end",
    "ev_citations",
    "ToolCategory",
    "ToolSpec",
    "register_tool",
    "list_tool_specs",
    "get_tool_spec",
    "get_tool",
    "get_tools",
    "tool_is_available",
    "unmet_requirements",
    "unregister_tool",
    "clear_tools",
]
