"""测试桩：替换 app.settings.search 里用到的 httpx，让联网工具全程不发真请求

用法见 tests/test_web_search_tool.py / test_read_url_tool.py。
只替换 settings.search 模块命名空间里的 httpx 属性，不动全局 httpx ——
后者会连带影响 settings.llm 的连通性探测，那不属于被测范围。
"""

import json
from types import SimpleNamespace

import httpx


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if payload is None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("body is not json")
        return self._payload


class FakeClient:
    """记录最后一次请求，返回预设响应或抛出预设异常"""

    sent: dict = {}
    response = FakeResponse(payload={"results": []})
    error: Exception | None = None

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, *, headers=None, **kwargs):
        # 真实调用是 post(url, json=..., headers=...)；从 kwargs 取 json，
        # 免得与模块顶部的 json 同名
        type(self).sent = {"url": url, "body": kwargs.get("json"), "headers": headers}
        if type(self).error is not None:
            raise type(self).error
        return type(self).response


def install_fake_httpx(monkeypatch, settings, *, response=None, error=None):
    """让 settings_search 用假客户端；返回 FakeClient 以便断言 sent"""
    from app.settings import search as settings_search

    FakeClient.sent = {}
    FakeClient.response = response or FakeResponse(payload={"results": []})
    FakeClient.error = error
    monkeypatch.setattr(settings_search, "get_search_settings", lambda: settings)
    monkeypatch.setattr(
        settings_search,
        "httpx",
        SimpleNamespace(
            AsyncClient=FakeClient,
            TimeoutException=httpx.TimeoutException,
            HTTPError=httpx.HTTPError,
        ),
    )
    return FakeClient
