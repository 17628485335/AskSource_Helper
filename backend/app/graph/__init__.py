"""Graph 模块包：工具注册表与流式通信协议（具体工具在 app/tools，会话在 app/session）

这里只放「图怎么拿到工具、图的事件怎么翻译成前后端协议」的基础设施：
- tools.py：@register_tool 装饰器 + ToolSpec 注册表 + tool_is_available 可用性探测
- stream_protocol.py：astream_events(v2) → SSE 协议事件（token/reasoning/tool_start/tool_end/citations）
- 具体工具一律写在 app/tools/ 下（一个工具一个文件，导入该包即完成注册）
"""

from .stream_protocol import EVENT_TYPES, translate
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
    "EVENT_TYPES",
    "translate",
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
