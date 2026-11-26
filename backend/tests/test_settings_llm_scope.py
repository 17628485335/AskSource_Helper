"""模型配置权限收敛后的装配测试（不依赖 MySQL）

要守住的三件事：
1. 带密钥的 /settings/llm 读写与连通性探测都必须挂 get_current_admin；
2. 给对话框用的 /settings/models 登录即可读，且响应里绝不出现密钥字段；
3. ChatManager 取配置不再接受 user_id —— 配置是全局一份，不是每人一份。
"""

import inspect

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.chat import ChatManager, ModelAgent
from app.main import app
from app.settings.schemas import ProviderWrite

client = TestClient(app)


def _all_routes():
    """递归展开路由：新版 FastAPI 把 include_router 的结果包成 _IncludedRouter，
    真实的 APIRoute 挂在它的 original_router.routes 里，只扫 app.routes 一个也找不到"""
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        if isinstance(r, APIRoute):
            yield r
            continue
        inner = getattr(r, "original_router", None) or getattr(r, "routes", None)
        if inner is not None:
            stack.extend(list(inner.routes) if hasattr(inner, "routes") else inner)


def _route(path: str, method: str) -> APIRoute:
    for r in _all_routes():
        if r.path == path and method in r.methods:
            return r
    raise AssertionError(f"未找到路由 {method} {path}")


def _dependency_names(route: APIRoute) -> set[str]:
    """递归收集路由链上所有依赖函数的名字（子依赖在 dependant.dependencies 里）"""
    seen: set[str] = set()
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            seen.add(getattr(dep.call, "__name__", ""))
        stack.extend(dep.dependencies)
    return seen


def test_llm_write_routes_require_admin():
    for path, method in (
        ("/settings/llm", "GET"),
        ("/settings/llm", "PUT"),
        ("/settings/llm/test", "POST"),
    ):
        assert "get_current_admin" in _dependency_names(_route(path, method)), (
            f"{method} {path} 丢了管理员闸门"
        )


def test_chat_models_route_only_requires_login():
    deps = _dependency_names(_route("/settings/models", "GET"))
    assert "get_current_user" in deps
    assert "get_current_admin" not in deps, "模型列表不该只有管理员能看"


def test_chat_models_response_has_no_secret_fields():
    schema = app.openapi()["components"]["schemas"]["ChatModelOption"]["properties"]
    assert {"base_url", "api_key"}.isdisjoint(schema), schema
    # 可用性必须随列表一起下发：否则前端只能让用户选一个一发就报错的模型
    assert {"available", "unavailable_reason", "supports_thinking"} <= set(schema), schema


def test_unauthenticated_chat_models_is_401():
    assert client.get("/settings/models").status_code == 401


def test_tools_route_only_requires_login():
    deps = _dependency_names(_route("/settings/tools", "GET"))
    assert "get_current_user" in deps
    assert "get_current_admin" not in deps, "工具列表不该只有管理员能看"


def test_unauthenticated_tools_is_401():
    assert client.get("/settings/tools").status_code == 401


def test_tools_response_has_display_label():
    schema = app.openapi()["components"]["schemas"]["ToolOut"]["properties"]
    assert {"name", "label", "icon"} <= set(schema), schema


def test_provider_write_strips_identifiers():
    """写入端就得去空格：表里的键必须与 ChatManager 建池用的键一致

    否则管理员多敲一个空格，下拉里选得到、一发就报「未接入模型」。
    """
    p = ProviderWrite(platform=" deepseek ", default_model=" deepseek-chat ", api_key=" sk-1 ")
    assert (p.platform, p.default_model, p.api_key) == ("deepseek", "deepseek-chat", "sk-1")


def test_config_resolution_has_no_user_dimension():
    """模型池的公开面不再有「每用户一份」的痕迹，也不能留下已退役的取实例入口"""
    for fn in (ChatManager.load, ChatManager.get, ChatManager.reload, ChatManager.pick):
        assert "user_id" not in inspect.signature(fn).parameters, fn
    # 每请求建实例那条路已封死：只允许从常驻池里 pick
    assert not any(hasattr(ChatManager, n) for n in ("create", "resolve_config", "clear_cache"))
    # 服务级 .env 单例也已整体删除
    assert not any(hasattr(ChatManager, n) for n in ("shared", "reset_shared", "env_config"))
    # 对话能力在单模型实例上，不在池上
    assert callable(ModelAgent.stream) and not hasattr(ChatManager, "stream")
