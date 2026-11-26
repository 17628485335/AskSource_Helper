"""联网搜索工具：把 Tavily 命中结果压成给模型看的文本，并附一份结构化引用

分工：
- app/settings/search.py —— 配置与传输（项目规范要求外部 API 适配集中在 settings）
- app/tools/citations.py —— 引用编号与 artifact 形状，工具与 SSE 层共用的约定
- 本文件 —— 模型看到什么：工具名、description（模型据此决定要不要调）、入参、返回文本

返回用 content_and_artifact：正文（带编号的结果）发给模型，引用结构走 artifact
（不占上下文，但能在流式层被取出来变成前端卡片）。
"""

from collections.abc import Sequence
from typing import Annotated, Any, ClassVar

from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import InjectedState
from pydantic import BaseModel, Field

from app.graph.tools import ToolCategory, register_tool
from app.settings.search import SearchError, SearchResult, search_enabled, tavily_search

from .citations import Citation, build_artifact, citation_offset

# 单条摘要的截断长度。搜索引擎一条结果动辄上千字，全塞进 ReAct 上下文既淹没模型，
# 又会让这一轮之后的每次模型调用都变贵（工具结果会留在消息里反复送上去）。
SNIPPET_LIMIT = 300
# 允许模型指定的最大条数，超过就夹回来
MAX_RESULTS_LIMIT = 5


class WebSearchArgs(BaseModel):
    """工具入参：把条数交给模型，比只给一个 query 更好用

    故意不加 ``le=`` 硬约束：模型传了 8 就 rejected，它得先错一轮才知道上限，
    白浪费一次调用。上限写在 description 里告知，实际越界由 _arun 夹回来。

    ``state`` 由 InjectedState 注入、对模型不可见（实测转换出的 schema 只剩 query
    和 max_results），用来把「本轮已经用到几号」传进工具，让多次搜索的编号续上。
    """

    query: str = Field(description="检索词，尽量具体；问时效信息时带上年份或「最新」")
    max_results: int = Field(
        default=3, description=f"返回几条结果，1~{MAX_RESULTS_LIMIT} 条，默认 3 条"
    )
    state: Annotated[dict, InjectedState] = Field(default_factory=dict)


def format_results(
    query: str, results: Sequence[SearchResult], start: int = 1
) -> tuple[str, list[Citation]]:
    """返回（给模型的文本, 引用列表）。编号从 start 续，保证一轮之内 [n] 唯一。"""
    citations: list[Citation] = []
    lines = [f"检索「{query}」得到 {len(results)} 条结果（编号 [n] 可在回答中直接引用）："]
    for offset, item in enumerate(results):
        index = start + offset
        title = " ".join((item.title or "（无标题）").split())
        # 压缩空白：摘要里夹着换行会把「一条结果」撑成好几行，模型难以对齐编号
        snippet = " ".join(item.content.split())[:SNIPPET_LIMIT]
        date = item.published_date[:10]
        suffix = f" · 发布于 {date}" if date else ""
        lines.append(f"[{index}] {title}{suffix}\n    {item.url}\n    {snippet}")
        citations.append(
            Citation(
                index=index,
                title=title,
                url=item.url,
                snippet=snippet,
                published_date=date,
                kind="search",
            )
        )
    return "\n".join(lines), citations


@register_tool(
    tags=["search"],
    category=ToolCategory.SEARCH,
    icon="globe",
    label="联网搜索",
    max_calls=3,
    requires_env=["TAVILY_API_KEY"],
    example='web_search(query="2026 年诺贝尔物理学奖", max_results=3)',
)
class WebSearchTool(BaseTool):
    """联网搜索：本轮没有联网能力时，模型只能靠训练数据猜时效信息"""

    # 元数据写在类字段最直白（装饰器也能传 name/description，但那是写回类默认值再 rebuild）
    name: str = "web_search"
    description: str = (
        "联网搜索实时网页资料。输入检索词，返回若干条带编号的结果「[n] 标题 / 链接 / 摘要」。"
        "遇到时效性信息（新闻、价格、版本、比分、政策法规、近期数据）或你不确定、"
        "可能已经过时的事实，必须先调用本工具再回答；"
        "回答中引用时写成 [n]，末尾列出采用的编号，不要编造来源。"
    )
    args_schema: ClassVar[Any] = WebSearchArgs
    # 正文给模型，引用给前端
    response_format: str = "content_and_artifact"

    @classmethod
    def available(cls) -> bool:
        """没配密钥就别挂进模型图：调了只会拿回一句报错，白烧一轮 token 和几秒"""
        return search_enabled()

    async def _arun(  # type: ignore[override]
        self, query: str, max_results: int = 3, state: dict | None = None
    ) -> tuple[str, dict[str, Any]]:
        # 夹而不是拒：模型给的条数不可靠，但「想要更多结果」的意图是清楚的
        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(limit, MAX_RESULTS_LIMIT))

        try:
            results = await tavily_search(query, max_results=limit)
        except SearchError as exc:
            # 这里绝不能往外抛：langchain 默认 handle_tool_error=False，异常会顺着
            # 图抛到 ModelAgent.stream()，被 service 转成 error 事件 —— 整轮回答直接作废。
            # 返回一段说明文本，模型会自己改用已有知识继续答。
            return (
                f"联网搜索失败：{exc}。请基于你已知的信息回答，并说明无法核实最新情况。",
                build_artifact([], tool=self.name),
            )
        if not results:
            return (
                "联网搜索没有命中任何结果，可以换一个更简短的检索词再试一次。",
                build_artifact([], tool=self.name),
            )

        # 编号接着本轮已用过的最大值往下排，模型连搜两次也不会出现两个 [1]
        start = citation_offset(state) + 1
        text, citations = format_results(query.strip(), results, start=start)
        return text, build_artifact(citations, query=query.strip(), tool=self.name)

    def _run(  # type: ignore[override]
        self, query: str, max_results: int = 3, state: dict | None = None
    ) -> tuple[str, dict[str, Any]]:
        # 整条链路都是 async（FastAPI + 异步 DB + astream），create_agent 走的是 _arun。
        # 留个明确的报错而不是静默返回空文本，免得将来有人同步调用时以为「搜索坏了」。
        raise NotImplementedError("web_search 只提供异步实现，请用 ainvoke/astream")
