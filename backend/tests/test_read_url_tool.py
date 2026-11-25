"""read_url 工具：地址过滤、正文截断、引用续号与降级（不发真请求）

重点守两处：
- 地址过滤（只留 http(s)、截到上限）——这是把模型输入交给外部抓取前的必要闸门；
- 失败同样只返回文本，不抛异常（理由同 web_search）。
"""

import asyncio

import pytest

from app.settings.search import (
    MAX_EXTRACT_URLS,
    ExtractedPage,
    SearchError,
    SearchSettings,
    tavily_extract,
)
from app.tools import read_url as read_url_module
from app.tools.read_url import (
    PAGE_CHAR_LIMIT,
    ReadUrlTool,
    _clean,
    _title_from_url,
    format_pages,
)
from tests._stubs import FakeClient, FakeResponse, install_fake_httpx

KEYED = SearchSettings(tavily_api_key="tvly-test")


def _one_page_response():
    """只关心请求体的用例也得给条像样响应，否则抽取层会当成全失败而抛错"""
    return FakeResponse(payload={"results": [{"url": "https://a.example/x", "raw_content": "正文"}]})


# ---------------------------------------------------------------- 抽取层


def test_missing_key_fails_before_any_request(monkeypatch):
    install_fake_httpx(monkeypatch, SearchSettings())
    with pytest.raises(SearchError, match="未配置搜索密钥"):
        asyncio.run(tavily_extract(["https://a"]))
    assert FakeClient.sent == {}


def test_only_http_urls_survive_and_count_is_capped(monkeypatch):
    """模型能拼出 javascript: / file: / 内网地址，这里先过一道，且不许一次来一堆"""
    install_fake_httpx(monkeypatch, KEYED, response=_one_page_response())
    urls = [
        "https://a.example/x",
        "  https://b.example/y  ",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://c.example/z",
        "https://d.example/w",
        "https://e.example/v",
        "https://f.example/u",
    ]
    asyncio.run(tavily_extract(urls))

    sent = FakeClient.sent
    assert sent["url"] == "https://api.tavily.com/extract"
    assert sent["body"]["urls"] == [
        "https://a.example/x",
        "https://b.example/y",
        "http://c.example/z",
        "https://d.example/w",
        "https://e.example/v",
    ]
    assert len(sent["body"]["urls"]) == MAX_EXTRACT_URLS
    assert sent["body"]["format"] == "markdown"
    assert sent["body"]["include_published_date"] is True
    assert "query" not in sent["body"]


def test_query_switches_to_relevant_chunks(monkeypatch):
    """带 query 时让上游只回相关片段，正文量能省一个量级"""
    install_fake_httpx(monkeypatch, KEYED, response=_one_page_response())
    asyncio.run(tavily_extract(["https://a"], query="  股价多少  "))
    assert FakeClient.sent["body"]["query"] == "股价多少"
    assert FakeClient.sent["body"]["chunks_per_source"] == 3


def test_no_usable_url_is_rejected(monkeypatch):
    install_fake_httpx(monkeypatch, KEYED)
    with pytest.raises(SearchError, match="没有可读取的 http"):
        asyncio.run(tavily_extract(["", "   ", "ftp://x"]))
    assert FakeClient.sent == {}


def test_pages_and_failures_are_separated(monkeypatch):
    install_fake_httpx(
        monkeypatch,
        KEYED,
        response=FakeResponse(
            payload={
                "results": [
                    {"url": "https://a", "raw_content": "# 标题\n\n正文"},
                    {"url": "https://b"},
                    "不是对象",
                ],
                "failed_results": [{"url": "https://c", "error": "blocked"}, "不是对象"],
            }
        ),
    )
    pages, failed = asyncio.run(tavily_extract(["https://a", "https://b"]))
    assert [p.url for p in pages] == ["https://a", "https://b"]
    assert pages[1].raw_content == ""
    assert failed == ["https://c"]


def test_total_failure_without_detail_raises(monkeypatch):
    """上游既没给 results 也没给 failed_results：说清楚，别让工具返回空文本"""
    install_fake_httpx(monkeypatch, KEYED, response=FakeResponse(payload={"results": []}))
    with pytest.raises(SearchError, match="都没能读出正文"):
        asyncio.run(tavily_extract(["https://a"]))


def test_extract_timeout_has_its_own_message(monkeypatch):
    import httpx

    install_fake_httpx(monkeypatch, KEYED, error=httpx.TimeoutException("t"))
    with pytest.raises(SearchError, match="读取网页超时"):
        asyncio.run(tavily_extract(["https://a"]))


# ---------------------------------------------------------------- 工具层


def test_title_falls_back_from_slug_to_domain():
    assert _title_from_url("https://en.wikipedia.org/wiki/Artificial_intelligence") == "Artificial intelligence"
    assert _title_from_url("https://example.com/news/openai-gpt-5.html") == "openai gpt 5"
    assert _title_from_url("https://www.a.cn/") == "a.cn"
    assert _title_from_url("https://a.cn/?q=1") == "a.cn"
    # 路径末段太短（一个字母、纯数字）不像标题，宁可用域名
    assert _title_from_url("https://a.cn/x") == "a.cn"
    assert _title_from_url("https://a.cn/123") == "a.cn"


def test_format_pages_truncates_and_numbers():
    pages = [
        ExtractedPage(url="https://a.example/deep-copy", raw_content="段落" + "字" * 4000),
        ExtractedPage(url="https://b.example", raw_content="短正文", published_date="2026-01-02T00:00:00Z"),
    ]
    text, citations = format_pages(pages, ["https://c"], start=3)

    assert "[3] deep copy" in text
    assert "[4] b.example · 发布于 2026-01-02" in text
    assert "……（正文已截断）" in text
    assert "以下地址没能读到正文：https://c" in text
    body = text.split("https://a.example/deep-copy\n    ")[1].split("\n")[0]
    assert body.startswith("段落") and len(body.replace("……（正文已截断）", "")) == PAGE_CHAR_LIMIT
    assert [c.index for c in citations] == [3, 4]
    assert all(c.kind == "page" for c in citations)
    assert citations[1].title == "b.example"


def test_clean_collapses_blank_lines_and_flattens_snippet():
    """markdown 导出动辄三五个连续换行，白白占掉截断额度"""
    assert _clean("首段\n\n\n\n\n尾段\n  \n") == "首段\n\n尾段"
    text, citations = format_pages(
        [ExtractedPage(url="https://a.example/post", raw_content="首段\n\n\n\n第二段有\t点长" * 40)], []
    )
    assert "\n\n\n" not in text
    assert "\n" not in citations[0].snippet and "  " not in citations[0].snippet
    assert len(citations[0].snippet) <= 160


def test_tool_degrades_instead_of_raising(monkeypatch):
    async def boom(urls, **kwargs):
        raise SearchError("读取网页超时（15s）")

    monkeypatch.setattr(read_url_module, "tavily_extract", boom)
    text, artifact = asyncio.run(ReadUrlTool()._arun(["https://a"]))
    assert "读取网页失败：读取网页超时" in text and "web_search" in text
    assert artifact == {"citations": [], "tools": "read_url"}

    async def empty(urls, **kwargs):
        return [], ["https://a"]

    monkeypatch.setattr(read_url_module, "tavily_extract", empty)
    text, artifact = asyncio.run(ReadUrlTool()._arun(["https://a"]))
    assert "都没有正文" in text and artifact["citations"] == []


def test_tool_reads_pages_and_shares_numbering_namespace(monkeypatch):
    """编号从本轮已用掉的最大值后续上，与 web_search 同一套号"""

    async def hit(urls, *, query=""):
        return [ExtractedPage(url=url, raw_content="正文 " * 10) for url in urls], []

    monkeypatch.setattr(read_url_module, "tavily_extract", hit)
    tool = ReadUrlTool()

    text, artifact = asyncio.run(tool._arun(["https://x.example/page-one"]))
    assert "[1] page one" in text and artifact["citations"][0]["url"] == "https://x.example/page-one"

    from langchain_core.messages import ToolMessage

    echoed = ToolMessage(content=text, tool_call_id="c1", name="read_url", artifact=artifact)
    # 前面已有 web_search 用过 1~2 号：本轮该从 3 开始
    prior = {"citations": [{"index": 2, "url": "https://old"}]}
    older = ToolMessage(content="", tool_call_id="c0", name="web_search", artifact=prior)
    second, next_artifact = asyncio.run(
        tool._arun(["https://y.example/alpha"], state={"messages": [older, echoed]})
    )
    assert "[3] alpha" in second
    assert next_artifact["citations"][0]["index"] == 3


def test_registered_and_injected_state_hidden_from_model():
    from app.graph import list_tool_specs

    assert "read_url" in [s.name for s in list_tool_specs()]
    tool = ReadUrlTool()
    assert set(tool.args) == {"urls", "query"}, "InjectedState 字段漏进了模型可见入参"
    assert tool.response_format == "content_and_artifact"
    assert "read_url" in {s.name for s in list_tool_specs(["search"])}


def test_sync_call_fails_loudly():
    with pytest.raises(NotImplementedError):
        ReadUrlTool()._run(["https://a"])
