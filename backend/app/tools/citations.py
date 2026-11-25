"""工具引用的编号与结构

为什么要单独一层「本轮全局编号」：模型经常连搜两次（多跳问题），如果每次调用都从
[1] 开始，回答里那句「据 [1]」就同时指向两个来源，前端卡片怎么排都消不掉歧义。
所以编号在一个回答轮次内递增续号 —— 工具从图状态里读回本轮已用掉的最大编号。

结构走 ToolMessage.artifact 而不是解析工具返回的正文：
- artifact 不会发给模型，不占上下文；正文必须发（模型靠它回答）；
- 实测 artifact 能原样活到 stream_mode="messages"，比正则扒正文可靠得多。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CITATION_KEY",
    "Citation",
    "build_artifact",
    "citation_offset",
    "extract_citations",
]

# artifact 里放引用列表的键名
CITATION_KEY = "citations"


class Citation(BaseModel):
    """一条可被引用的来源；index 就是模型正文里写的 [n]"""

    model_config = ConfigDict(frozen=True)

    index: int
    title: str = ""
    url: str = ""
    snippet: str = ""
    published_date: str = ""
    # search = 搜索结果条目，page = read_url 实际打开过的页面
    kind: str = "search"

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


def extract_citations(message: Any) -> list[dict[str, Any]]:
    """从一条 ToolMessage（或任何带 artifact 的对象）里取引用；形状不对一律当没有"""
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return []
    items = artifact.get(CITATION_KEY)
    if not isinstance(items, list):
        return []
    # 没有 url 的条目前端点不动，直接不认（也算不上「引用」）
    return [item for item in items if isinstance(item, dict) and item.get("url")]


def citation_offset(state: Any) -> int:
    """本轮已用掉的最大编号，没有则 0。

    state 是 InjectedState 注入的图状态（含 messages）。工具实例是整池共用的，
    计数绝不能挂在 self 上 —— 那会让并发请求互相串号；只能从会话状态里推。
    """
    messages = state.get("messages") if isinstance(state, dict) else None
    highest = 0
    for message in messages or []:
        for item in extract_citations(message):
            try:
                highest = max(highest, int(item.get("index") or 0))
            except (TypeError, ValueError):
                continue
    return highest


def build_artifact(citations: list[Citation], *, query: str = "", tool: str = "") -> dict[str, Any]:
    """组装 artifact：引用列表 + 触发它的检索词（前端卡片标题用得上）"""
    payload: dict[str, Any] = {CITATION_KEY: [c.as_dict() for c in citations]}
    if query:
        payload["query"] = query
    if tool:
        payload["tools"] = tool
    return payload
