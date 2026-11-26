"""读取网页正文工具：搜索摘要撑不起细节时，把页面完整读进来

与 web_search 共用一份引用编号空间（都从本轮已用掉的最大编号后续号），所以模型说的
[3] 只有一个指向，无论它来自搜索结果还是被打开过的页面。

正文走 Tavily /extract 而不是本机 httpx：见 app/settings/search.py 里 tavily_extract
的说明（省 HTML 解析 + 不当 SSRF 跳板）。
"""

import re
from collections.abc import Sequence
from typing import Annotated, Any, ClassVar
from urllib.parse import unquote, urlparse

from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import InjectedState
from pydantic import BaseModel, Field

from app.graph.tools import ToolCategory, register_tool
from app.settings.search import (
    MAX_EXTRACT_URLS,
    ExtractedPage,
    SearchError,
    search_enabled,
    tavily_extract,
)

from .citations import Citation, build_artifact, citation_offset

# 单页正文送给模型的上限。一页 markdown 轻松上万字，几页就能把上下文顶满，
# 而且之后每一轮都要把这些字重新发一遍。
PAGE_CHAR_LIMIT = 2500
# 引用卡片上显示的一行摘要长度
SNIPPET_LIMIT = 160


class ReadUrlArgs(BaseModel):
    """urls 用列表而不是单个地址：模型经常一次想读两三页，逐个调用要多轮开销"""

    urls: list[str] = Field(
        description=f"要读取的网页地址，1~{MAX_EXTRACT_URLS} 个，取自 web_search 结果里的链接"
    )
    query: str = Field(
        default="",
        description="可选：只关心某个具体问题时填它，上游只回相关片段而不是整页正文",
    )
    state: Annotated[dict, InjectedState] = Field(default_factory=dict)


def _clean(text: str) -> str:
    """压掉页面里成片的空行；markdown 导出动辄三五个连续换行"""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _title_from_url(url: str) -> str:
    """/extract 不返回标题，只能从地址凑一个能看的：优先路径末段，退化到域名"""
    parsed = urlparse(url)
    tail = unquote(parsed.path.rstrip("/")).split("/")[-1].strip()
    tail = re.sub(r"\.(html?|php|aspx?|shtml)$", "", tail, flags=re.I)
    tail = tail.replace("-", " ").replace("_", " ").strip()
    if len(tail) >= 3 and re.search(r"[A-Za-z\u4e00-\u9fff]", tail):
        return tail[:80]
    return (parsed.netloc or url).replace("www.", "")


def format_pages(
    pages: Sequence[ExtractedPage], failed: Sequence[str], start: int = 1
) -> tuple[str, list[Citation]]:
    """正文 + 引用；编号从 start 续，一页一条"""
    citations: list[Citation] = []
    lines = [f"已读取 {len(pages)} 个页面正文（编号 [n] 可在回答中直接引用）："]
    for offset, page in enumerate(pages):
        index = start + offset
        title = _title_from_url(page.url)
        body = _clean(page.raw_content)
        clipped = body[:PAGE_CHAR_LIMIT]
        suffix = f" · 发布于 {page.published_date[:10]}" if page.published_date else ""
        tail = "……（正文已截断）" if len(body) > PAGE_CHAR_LIMIT else ""
        lines.append(f"[{index}] {title}{suffix}\n    {page.url}\n    {clipped}{tail}")
        citations.append(
            Citation(
                index=index,
                title=title,
                url=page.url,
                snippet=" ".join(body.split())[:SNIPPET_LIMIT],
                published_date=page.published_date[:10],
                kind="page",
            )
        )
    if failed:
        lines.append("以下地址没能读到正文：" + "、".join(failed))
    return "\n".join(lines), citations


@register_tool(
    tags=["search"],
    category=ToolCategory.SEARCH,
    icon="file-text",
    label="网页正文读取",
    requires_env=["TAVILY_API_KEY"],
    example='read_url(urls=["https://example.com/post"], query="上市日期")',
)
class ReadUrlTool(BaseTool):
    """配套 web_search 用：摘要给不了细节时打开原文"""

    name: str = "read_url"
    description: str = (
        "读取指定网页的正文（已剔掉导航、广告和评论，markdown 格式）。"
        "当 web_search 返回的摘要不足以回答、或需要原文措辞与完整数据时调用，"
        f"地址取自搜索结果的链接，一次最多 {MAX_EXTRACT_URLS} 个。"
        "返回内容带同样的编号 [n]，引用方式与搜索结果一致。"
    )
    args_schema: ClassVar[Any] = ReadUrlArgs
    response_format: str = "content_and_artifact"

    @classmethod
    def available(cls) -> bool:
        """与 web_search 同一个密钥：上游没配好就别挂进图"""
        return search_enabled()

    async def _arun(  # type: ignore[override]
        self, urls: list[str], query: str = "", state: dict | None = None
    ) -> tuple[str, dict[str, Any]]:
        try:
            pages, failed = await tavily_extract(urls or [], query=query or "")
        except SearchError as exc:
            # 同 web_search：往外抛会让整轮回答直接作废，只能降级成一段说明文本
            return (
                f"读取网页失败：{exc}。请改用 web_search 的摘要回答，并注明未能核实原文。",
                build_artifact([], tool=self.name),
            )
        if not pages:
            return (
                "这些地址都没有正文（多半是需要登录、被反爬拦截或纯前端渲染的页面）。"
                "可以换 web_search 结果里的其他链接试试。",
                build_artifact([], tool=self.name),
            )

        start = citation_offset(state) + 1
        text, citations = format_pages(pages, failed, start=start)
        return text, build_artifact(citations, query=(query or "").strip(), tool=self.name)

    def _run(  # type: ignore[override]
        self, urls: list[str], query: str = "", state: dict | None = None
    ) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError("read_url 只提供异步实现，请用 ainvoke/astream")
