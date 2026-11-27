"""上下文 token 计数。

统一的 token 计数入口，供历史压缩、上下文预算等场景使用。

计数用 tiktoken 的 cl100k_base 词表：项目接的是 DeepSeek / 硅基流动 / 阿里百炼
等 OpenAI 兼容端点，它们各有自己的分词器，cl100k_base 算出的仍是近似值，
但比按字符数折半稳得多（中文不再低估一半、英文不再高估两倍多）。

tiktoken 未安装或词表加载失败时降级到字符估算，保证离线/精简部署也能跑。
后续若接 OpenAI 官方模型，可按模型名切到对应词表，调用方不用改。
"""

import json
from functools import lru_cache
from typing import Any

_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def _get_encoding() -> Any | None:
    """带缓存地取词表：tiktoken 不可用或加载失败时返回 None，走降级估算。"""
    try:
        import tiktoken

        return tiktoken.get_encoding(_ENCODING_NAME)
    except Exception:
        return None


def _fallback_tokens(text: str) -> int:
    """降级估算：中文按 1 字 ≈ 1 token、英文按 4 字符 ≈ 1 token 折中。"""
    if not text:
        return 0
    chinese = sum("\u4e00" <= ch <= "\u9fff" for ch in text)
    return max(1, chinese + (len(text) - chinese) // 4)


def estimate_text_tokens(text: str) -> int:
    """估算一段文本的 token 数；空文本返回 0。"""
    if not text:
        return 0
    encoding = _get_encoding()
    if encoding is None:
        return _fallback_tokens(text)
    return len(encoding.encode(text))


def estimate_message_tokens(message: Any) -> int:
    """估算单条消息的 token，含多模态 content、工具调用 JSON 与 tool_call_id。"""
    parts: list[str] = []
    content = getattr(message, "content", "")
    if isinstance(content, str):
        parts.append(content)
    elif content:
        parts.append(json.dumps(content, ensure_ascii=False, default=str))

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append(json.dumps(tool_calls, ensure_ascii=False, default=str))

    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        parts.append(str(tool_call_id))

    return estimate_text_tokens("\n".join(parts))


def count_context_tokens(messages: list[Any]) -> int:
    """估算一段上下文（消息列表）的 token 总数。"""
    return sum(estimate_message_tokens(message) for message in messages)
