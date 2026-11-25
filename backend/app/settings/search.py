"""联网搜索适配层：数据源配置与 Tavily 调用

与 llm.py 同一套规矩：配置和传输集中在这里，工具层（app/tools/）只管把
结构化结果压成给模型看的文本。

密钥走 backend/.env 的 TAVILY_API_KEY。留空即视为「没接搜索」——
chat_manager.load_tools() 会把搜索与正文读取两个工具整个跳过，不挂进模型图，
而不是等模型调用时才报「未配置」，白烧一轮 token 和好几秒。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tavily 正式地址；.env 里的 TAVILY_BASE_URL 留空就用这个
DEFAULT_TAVILY_BASE_URL = "https://api.tavily.com"


class SearchSettings(BaseSettings):
    """联网搜索配置

    字段是平的（TAVILY_API_KEY 这种环境变量名直接对应），所以不需要像 LLMSettings
    那样设 env_nested_delimiter。extra="ignore" 会吞掉拼错的键，排查时先打印本对象
    的字段值而不是去翻 .env 文本。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tavily_api_key: str = ""
    # 默认留空：.env.example 里会写一行 TAVILY_BASE_URL= 供人覆盖，而 pydantic 会把
    # 空串当真值使，所以空串在 base_url 属性里回退内置地址（同 llm.py 的约定）
    tavily_base_url: str = ""
    # 搜索处于 ReAct 循环中间，太长的超时会把整轮回答拖死；失败让模型改用已有知识
    search_timeout: float = 8.0
    # 读整页比搜索慢（上游要真的去访问目标站点），单独给一个宽一点的超时
    extract_timeout: float = 15.0
    # 模型不指定条数时的默认值，同时也是工具层允许的上限
    search_max_results: int = 5

    @property
    def base_url(self) -> str:
        """生效的搜索服务地址（已去尾部斜杠）；走自建代理时在 .env 里覆盖"""
        return (self.tavily_base_url.strip() or DEFAULT_TAVILY_BASE_URL).rstrip("/")


@lru_cache
def get_search_settings() -> SearchSettings:
    """带缓存的配置单例（风格同 get_llm_settings）"""
    return SearchSettings()


class SearchResult(BaseModel):
    """一条命中结果"""

    model_config = ConfigDict(frozen=True)

    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0
    published_date: str = ""


class ExtractedPage(BaseModel):
    """一个页面抽出来的正文"""

    model_config = ConfigDict(frozen=True)

    url: str = ""
    raw_content: str = ""
    published_date: str = ""


# 一次最多读几个页：再多正文就撑爆上下文，模型也消化不了
MAX_EXTRACT_URLS = 5


class SearchError(RuntimeError):
    """联网检索不可用或调用失败（搜索与读网页两个接口共用）

    专门一个异常类而不是复用 RuntimeError：工具层要区分「可预期的失败」（转成文本
    让模型绕过）和「代码 bug」（该炸就炸，别藏进给模型的提示文本里）。
    """


def search_enabled() -> bool:
    """是否配了可用密钥（工具类据此决定是否挂进图）"""
    return bool(get_search_settings().tavily_api_key.strip())


def _error_detail(resp: httpx.Response) -> str:
    """把 Tavily 的错误体压成一句话：正常形状是 {"detail": {"error": "..."}}"""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            if detail.get("error"):
                return str(detail["error"])[:160]
            failed = detail.get("failed_results")
            if isinstance(failed, list) and failed:
                # /extract 把整个列表校验不过时走这个形状，没有 error 字段
                return f"{len(failed)} 个地址未通过校验"
            if detail:
                return json.dumps(detail, ensure_ascii=False)[:160]
        if isinstance(detail, str) and detail:
            return detail[:160]
    return (resp.text or "").strip().replace("\n", " ")[:160] or "无响应体"


def _raise_for_status(resp: httpx.Response) -> None:
    """把 Tavily 的状态码翻译成可读中文；2xx 直接返回。

    429/432/433 单独列出：它们意味着「重试也不会好」，文案得让模型明白
    这不是检索词的问题，不要换个词反复重试（每一次都在烧额度）。
    """
    if resp.status_code in (401, 403):
        raise SearchError(f"搜索密钥无效或被拒绝（HTTP {resp.status_code}）")
    if resp.status_code == 429:
        raise SearchError("调用过于频繁已被限流（HTTP 429），请稍后再试")
    if resp.status_code in (432, 433):
        raise SearchError(f"Tavily 配额已用完（HTTP {resp.status_code}），需检查套餐或余额")
    if resp.status_code >= 400:
        raise SearchError(f"接口返回 HTTP {resp.status_code}：{_error_detail(resp)}")


def _json_body(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise SearchError("接口返回的不是合法 JSON") from exc
    return data if isinstance(data, dict) else {}


def _as_result(item: dict[str, Any]) -> SearchResult:
    """上游字段类型不完全可信（score 可能是 None、date 可能是对象），逐项兜底"""
    score = item.get("score")
    return SearchResult(
        title=str(item.get("title") or "").strip(),
        url=str(item.get("url") or "").strip(),
        content=str(item.get("content") or "").strip(),
        score=float(score) if isinstance(score, (int, float)) else 0.0,
        published_date=str(item.get("published_date") or "").strip(),
    )


async def tavily_search(
    query: str,
    *,
    max_results: int | None = None,
    topic: Literal["general", "news"] = "general",
) -> list[SearchResult]:
    """调 Tavily POST /search 拿命中列表；任何失败都抛 SearchError（带可读原因）。

    include_answer 关掉：回答由对话模型出，再叠一层 Tavily 的综述只会占上下文。
    include_raw_content 关掉：整页正文动辄几十 KB，塞进 ReAct 上下文会让后续每轮都变贵。
    不重试：搜索挂在对话链路中间，失败时让模型改用已有知识就够，重试只会拖更久。
    """
    settings = get_search_settings()
    key = settings.tavily_api_key.strip()
    if not key:
        raise SearchError("未配置搜索密钥（.env 的 TAVILY_API_KEY）")
    if not (query or "").strip():
        raise SearchError("检索词为空")

    limit = max_results or settings.search_max_results
    payload: dict[str, Any] = {
        "query": query.strip(),
        "topic": topic,
        "search_depth": "basic",
        # 夹到 1~10：模型完全可能传个 100 上来，Tavily 侧也要按次计费
        "max_results": max(1, min(int(limit), 10)),
        "include_answer": False,
        "include_raw_content": False,
        "include_published_date": True,
    }
    url = settings.base_url + "/search"

    try:
        async with httpx.AsyncClient(timeout=settings.search_timeout) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {key}"}
            )
    except httpx.TimeoutException as exc:
        raise SearchError(f"搜索超时（{settings.search_timeout:.0f}s）") from exc
    except httpx.HTTPError as exc:
        raise SearchError(f"无法连接搜索服务：{exc.__class__.__name__}") from exc

    _raise_for_status(resp)
    results = _json_body(resp).get("results")
    if not isinstance(results, list):
        return []
    return [_as_result(item) for item in results if isinstance(item, dict)]


async def tavily_extract(
    urls: Sequence[str], *, query: str = ""
) -> tuple[list[ExtractedPage], list[str]]:
    """调 Tavily POST /extract 读网页正文，返回（成功的页面, 没能读的地址）。

    交给上游抓而不是本机 httpx 直连，一半是省掉 HTML 解析（导航/脚本/评论区都得剔），
    另一半是安全：地址由模型给出，本机去请求等于把内网（127.0.0.1、169.254.169.254、
    *.local）暴露给它，是典型的 SSRF 面。上游在它自己的集群里抓，我们的服务器不当跳板。
    """
    settings = get_search_settings()
    key = settings.tavily_api_key.strip()
    if not key:
        raise SearchError("未配置搜索密钥（.env 的 TAVILY_API_KEY）")

    # 只留 http(s)，并且截到上限：模型完全可能拼出一堆 javascript: 或 file: 地址
    wanted = [
        item.strip()
        for item in urls
        if isinstance(item, str) and item.strip().startswith(("http://", "https://"))
    ][:MAX_EXTRACT_URLS]
    if not wanted:
        raise SearchError("没有可读取的 http(s) 地址")

    payload: dict[str, Any] = {
        "urls": wanted,
        "extract_depth": "basic",
        "format": "markdown",
        "include_published_date": True,
    }
    if query.strip():
        # 带上 query 时上游只回相关片段而不是整页，正文量能省一个量级
        payload["query"] = query.strip()
        payload["chunks_per_source"] = 3

    try:
        async with httpx.AsyncClient(timeout=settings.extract_timeout) as client:
            resp = await client.post(
                settings.base_url + "/extract",
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.TimeoutException as exc:
        raise SearchError(f"读取网页超时（{settings.extract_timeout:.0f}s）") from exc
    except httpx.HTTPError as exc:
        raise SearchError(f"无法连接网页读取服务：{exc.__class__.__name__}") from exc

    _raise_for_status(resp)
    data = _json_body(resp)
    raw_pages = data.get("results")
    pages: list[ExtractedPage] = []
    for item in raw_pages if isinstance(raw_pages, list) else []:
        if not isinstance(item, dict):
            continue
        pages.append(
            ExtractedPage(
                url=str(item.get("url") or "").strip(),
                raw_content=str(item.get("raw_content") or ""),
                published_date=str(item.get("published_date") or "").strip(),
            )
        )

    raw_failed = data.get("failed_results")
    failed = [
        str(item.get("url") or "").strip()
        for item in (raw_failed if isinstance(raw_failed, list) else [])
        if isinstance(item, dict) and item.get("url")
    ]
    if not pages and not failed:
        raise SearchError("这些地址都没能读出正文")
    return pages, failed
