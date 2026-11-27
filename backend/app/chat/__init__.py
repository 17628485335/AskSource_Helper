"""Chat 模块包：ChatManager（模型池）+ ModelAgent（llm + tools + ReAct 图，只问模型）+ service（对话编排）+ SSE 流式问答接口

模型配置只有管理员能在「设置 - 模型」里维护。/chat 从常驻的 ChatManager 模型池里
按 (平台, 模型) 挑现成的 ModelAgent（深度思考是逐轮参数，不在键里）：池在启动 lifespan
里预热、管理员保存配置后重建，请求路径不建实例，也没有按用户解析的配置和 .env 服务级单例。
工具在建池时整池取一次（load_tools），逐模型直接复用。
"""

from .chat_manager import (
    DEFAULT_SYSTEM_PROMPT,
    ChatConfigError,
    ChatManager,
    ModelAgent,
    load_tools,
)
from .schemas import ChatRequest
from .service import stream_chat

__all__ = [
    "ChatRequest",
    "ChatManager",
    "ModelAgent",
    "ChatConfigError",
    "DEFAULT_SYSTEM_PROMPT",
    "load_tools",
    "stream_chat",
]
