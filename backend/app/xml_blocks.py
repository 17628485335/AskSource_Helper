"""XML 分块组装工具：统一 `<tag>...</tag>` 的拼装与块间空行。

系统提示词分段、会话摘要与历史消息等场景共用这里的规则，
保证标签成对、块间空行一致。
"""


def xml_block(tag: str, *parts: str | None, inline: bool = False) -> str:
    """把若干正文片段包进 `<tag>...</tag>`；None / 空白片段会被跳过。

    inline=True 输出单行 `<tag>正文</tag>`，用于日期这类独占一行的内容。
    """
    cleaned = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    if inline:
        return f"<{tag}>{' '.join(cleaned)}</{tag}>"
    body = "\n".join(cleaned)
    return f"<{tag}>\n{body}\n</{tag}>" if body else f"<{tag}>\n</{tag}>"


def join_blocks(*blocks: str | None) -> str:
    """用空行连接非空块（XML 块或普通文本），并去掉首尾空行。"""
    return "\n\n".join(block.strip("\n") for block in blocks if block and block.strip())
