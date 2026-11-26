"""联网搜索工具的注册、可用性、调用与降级（全程不碰网络）

守住四条后续容易被改断的性质：
1. 工具进了注册表，且注入字段不出现在模型可见的入参里；
2. 没配密钥时整池不挂这个工具，而不是等模型调用才失败；
3. 请求形状（Bearer 头、条数夹取、关掉 raw_content）与错误分流文案；
4. 搜索失败必须变成「给模型看的一段文本」，绝不能抛异常 ——
   抛出去会顺着 ReAct 图炸掉整轮回答（service 只能报 error）。

假 httpx 见 tests/_stubs.py。
"""

import asyncio

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.chat.chat_manager import load_tools
from app.graph import get_tools, list_tool_specs
from app.settings.search import SearchError, SearchSettings, SearchResult, tavily_search
from app.tools import web_search as search_module
from app.tools.citations import citation_start
from app.tools.web_search import (
    MAX_RESULTS_LIMIT,
    SNIPPET_LIMIT,
    WebSearchTool,
    format_results,
)
from tests._stubs import FakeClient, FakeResponse, install_fake_httpx


# ---------------------------------------------------------------- 注册与可用性


def test_search_tool_is_registered_without_leaking_injected_state():
    """工具进表；模型只看得到 query / max_results，注入的 state 不外露"""
    assert "web_search" in [s.name for s in list_tool_specs()]

    tool = next(t for t in get_tools() if t.name == "web_search")
    assert set(tool.args) == {"query", "max_results"}, "InjectedState 字段漏进了模型可见入参"
    assert tool.description and "联网搜索" in tool.description
    assert tool.response_format == "content_and_artifact"
    assert "web_search" in {s.name for s in list_tool_specs(["search"])}


def test_unavailable_tools_are_skipped_instead_of_breaking_the_pool(monkeypatch):
    """缺密钥 → 两个联网工具都跳过并留 warning；配上密钥 → 一起挂上"""
    from app.settings import search as settings_search

    monkeypatch.setattr(settings_search, "get_search_settings", lambda: SearchSettings())
    assert load_tools() == []

    keyed = SearchSettings(tavily_api_key="tvly-test")
    monkeypatch.setattr(settings_search, "get_search_settings", lambda: keyed)
    assert {t.name for t in load_tools()} == {"web_search", "read_url"}


def test_probe_treats_broken_availability_hook_as_unusable():
    """available() 自己抛异常时按不可用处理：宁可少一个工具也不能拖垮建池"""
    from types import SimpleNamespace

    from app.graph.tools import tool_is_available

    class Boom(WebSearchTool):
        name: str = "boom_tool"
        description: str = "占位"

        @classmethod
        def available(cls) -> bool:
            raise RuntimeError("配置读取失败")

    assert tool_is_available(Boom()) is False
    assert tool_is_available(SimpleNamespace()) is True  # 没实现就算可用


# ---------------------------------------------------------------- Tavily 调用层


def test_missing_key_or_query_fails_before_any_request(monkeypatch):
    """未配置时直接报错且不发请求（别拿着空 Authorization 去打上游）"""
    install_fake_httpx(monkeypatch, SearchSettings(tavily_base_url=""))
    with pytest.raises(SearchError, match="未配置搜索密钥"):
        asyncio.run(tavily_search("今天新闻"))
    assert FakeClient.sent == {}

    keyed = SearchSettings(tavily_api_key="tvly-test")
    install_fake_httpx(monkeypatch, keyed)
    with pytest.raises(SearchError, match="检索词为空"):
        asyncio.run(tavily_search("   "))


def test_blank_base_url_falls_back_to_default(monkeypatch):
    """.env.example 里 TAVILY_BASE_URL= 是空值，留空必须回退内置地址而不是拼出 /search"""
    install_fake_httpx(
        monkeypatch, SearchSettings(tavily_api_key="tvly-test", tavily_base_url="  ")
    )
    asyncio.run(tavily_search("q"))
    assert FakeClient.sent["url"] == "https://api.tavily.com/search"


def test_request_uses_bearer_auth_and_clamps_result_count(monkeypatch):
    """认证走 Bearer 头；条数夹到 1~10；raw_content / answer 关掉以省上下文"""
    install_fake_httpx(monkeypatch, SearchSettings(tavily_api_key="tvly-test"))
    asyncio.run(tavily_search("最新版本号", max_results=100))

    sent = FakeClient.sent
    assert sent["url"] == "https://api.tavily.com/search"
    assert sent["headers"]["Authorization"] == "Bearer tvly-test"
    assert sent["body"]["max_results"] == 10
    assert sent["body"]["include_raw_content"] is False
    assert sent["body"]["include_answer"] is False
    assert sent["body"]["query"] == "最新版本号"


def test_upstream_failures_become_readable_messages(monkeypatch):
    """状态码/异常分流：文案要能让模型和用户一眼看懂下一步做什么"""
    keyed = SearchSettings(tavily_api_key="tvly-test")
    cases = [
        (FakeResponse(status_code=401, payload={"detail": {"error": "bad key"}}), "密钥无效"),
        (
            FakeResponse(status_code=400, payload={"detail": {"error": "Invalid topic"}}),
            "Invalid topic",
        ),
        (FakeResponse(status_code=429, payload={"detail": {"error": "too many"}}), "限流"),
        (FakeResponse(status_code=432, payload={"detail": {"error": "plan"}}), "配额已用完"),
        (FakeResponse(status_code=500, text="gateway blew up"), "HTTP 500"),
        (FakeResponse(status_code=200, payload=None, text="<html>"), "不是合法 JSON"),
    ]
    for response, wanted in cases:
        install_fake_httpx(monkeypatch, keyed, response=response)
        with pytest.raises(SearchError) as exc:
            asyncio.run(tavily_search("q"))
        assert wanted in str(exc.value), f"{wanted} 没出现在 {exc.value}"

    install_fake_httpx(monkeypatch, keyed, error=httpx.TimeoutException("t"))
    with pytest.raises(SearchError, match="搜索超时"):
        asyncio.run(tavily_search("q"))

    install_fake_httpx(monkeypatch, keyed, error=httpx.ConnectError("refused"))
    with pytest.raises(SearchError, match="无法连接搜索服务"):
        asyncio.run(tavily_search("q"))


def test_results_are_parsed_defensively(monkeypatch):
    """上游字段类型不完全可信：缺 title、score=None、results 不是 list 都不能炸"""
    install_fake_httpx(
        monkeypatch,
        SearchSettings(tavily_api_key="tvly-test"),
        response=FakeResponse(
            payload={
                "results": [
                    {"title": "A", "url": "https://a", "content": "正文", "score": 0.9},
                    {"url": "https://b", "content": None, "score": None, "published_date": None},
                    "不是对象，直接丢",
                ]
            }
        ),
    )
    results = asyncio.run(tavily_search("q"))
    assert [r.url for r in results] == ["https://a", "https://b"]
    assert results[1].score == 0.0 and results[1].title == ""

    install_fake_httpx(
        monkeypatch,
        SearchSettings(tavily_api_key="tvly-test"),
        response=FakeResponse(payload={"results": None}),
    )
    assert asyncio.run(tavily_search("q")) == []


# ---------------------------------------------------------------- 工具层输出


def test_format_numbers_urls_and_truncates_snippets():
    """返回体积是硬约束：摘要截断、换行压平，但编号/标题/URL/日期都得留下"""
    long_content = "第一行\n第二行   继续\n" + "字" * 600
    results = [
        SearchResult(
            title="标题一",
            url="https://a",
            content=long_content,
            published_date="2026-11-20T00:00:00Z",
        ),
        SearchResult(title="", url="https://b", content="短"),
    ]
    text, citations = format_results("测试词", results, start=4)

    assert text.startswith("检索「测试词」得到 2 条结果")
    assert "[4] 标题一 · 发布于 2026-11-20" in text
    assert "[5] （无标题）" in text
    assert "https://a" in text and "https://b" in text
    assert "\n第二行" not in text  # 摘要内的换行被压平
    snippet = text.split("https://a\n    ")[1].split("\n")[0]
    assert len(snippet) == SNIPPET_LIMIT
    # artifact 侧的编号与正文一致，前端卡片才能对上
    assert [c.index for c in citations] == [4, 5]
    assert citations[0].kind == "search" and citations[0].published_date == "2026-11-20"


def test_tool_degrades_to_text_instead_of_raising(monkeypatch):
    """核心回归：搜索失败/无命中都返回文本 + 空引用，异常会炸掉整轮回答"""

    async def boom(query, **kwargs):
        raise SearchError("搜索超时（8s）")

    monkeypatch.setattr(search_module, "tavily_search", boom)
    text, artifact = asyncio.run(WebSearchTool()._arun("今天有什么新闻"))
    assert "联网搜索失败：搜索超时" in text and "已知的信息" in text
    assert artifact["citations"] == [] and artifact["tools"] == "web_search"


def test_parallel_search_calls_get_non_overlapping_citation_ranges():
    """同一批并行搜索必须预分配不重叠的 [n]，否则 6 条来源去重后只剩 3 条"""
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "A", "max_results": 3},
                        "id": "call_a",
                        "type": "tool_call",
                    },
                    {
                        "name": "web_search",
                        "args": {"query": "B", "max_results": 3},
                        "id": "call_b",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    }
    assert citation_start(state, "call_a") == 1
    assert citation_start(state, "call_b") == 4


def test_tool_clamps_out_of_range_counts_instead_of_rejecting(monkeypatch):
    """模型传 99 / 0 / 非数字都得夹进合法区间，而不是先吃一次校验错误再重试"""
    seen: list[int] = []

    async def hit(query, *, max_results=None, **kwargs):
        seen.append(max_results)
        return [SearchResult(title="T", url="https://u", content="C")]

    monkeypatch.setattr(search_module, "tavily_search", hit)
    tool = WebSearchTool()
    for raw, want in [(99, MAX_RESULTS_LIMIT), (0, 1), (-3, 1), (None, 3), ("abc", 3), (2, 2)]:
        asyncio.run(tool._arun("q", max_results=raw))
        assert seen[-1] == want, f"max_results={raw!r} 应被夹成 {want}，实际 {seen[-1]}"


def test_tool_numbers_continue_from_previous_calls(monkeypatch):
    """同一轮里第二次搜索从 [3] 起，正文里的 [1] 才不会被两个来源同时指向"""

    async def hit(query, *, max_results=None, **kwargs):
        return [
            SearchResult(title=f"T{query}", url=f"https://u/{query}", content="C"),
            SearchResult(title=f"U{query}", url=f"https://v/{query}", content="C"),
        ]

    monkeypatch.setattr(search_module, "tavily_search", hit)
    tool = WebSearchTool()

    first, art1 = asyncio.run(tool._arun("a"))
    assert "[1] Ta" in first and [c["index"] for c in art1["citations"]] == [1, 2]

    # 图状态里已有一条带 artifact 的 ToolMessage，模拟本轮第一次调用之后的状态
    echoed = ToolMessage(
        content=first, tool_call_id="call_1", name="web_search", artifact=art1
    )
    second, art2 = asyncio.run(tool._arun("b", state={"messages": [echoed]}))
    assert "[3] Tb" in second and [c["index"] for c in art2["citations"]] == [3, 4]


def test_tool_carries_query_into_artifact_for_ui(monkeypatch):
    """artifact 里带上检索词，前端卡片标题才能写「关于 xxx 的 3 条来源」"""

    async def hit(query, *, max_results=None, **kwargs):
        return [SearchResult(title="T", url="https://u", content="C")]

    monkeypatch.setattr(search_module, "tavily_search", hit)
    _, artifact = asyncio.run(WebSearchTool()._arun("  最新油价  "))
    assert artifact["query"] == "最新油价"


def test_sync_call_fails_loudly():
    """同步入口要响亮失败，不能静默返回空串让人误判成「搜索没结果」"""
    with pytest.raises(NotImplementedError):
        WebSearchTool()._run("q")
