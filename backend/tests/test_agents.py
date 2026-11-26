"""agents / agent_prompts 的注册、权限与表结构守门测试（不连 MySQL）"""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.agents.models import Agent, AgentPrompt
from app.main import app

client = TestClient(app)


def _all_routes():
    """新版 FastAPI 把 include_router 包成 _IncludedRouter，要往下递归一层"""
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None) or getattr(route, "routes", None)
        if inner is not None:
            stack.extend(list(inner.routes) if hasattr(inner, "routes") else inner)


def _dependency_names(route) -> set[str]:
    seen: set[str] = set()
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            seen.add(getattr(dep.call, "__name__", ""))
        stack.extend(dep.dependencies)
    return seen


def test_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/agents" in paths
    assert "/agents/{agent_id}" in paths
    assert "/agents/{agent_id}/prompts" in paths
    assert "/agents/{agent_id}/prompts/{version}/activate" in paths


def test_read_is_login_scoped():
    route = next(r for r in _all_routes() if r.path == "/agents" and "GET" in r.methods)
    deps = _dependency_names(route)
    assert "get_current_user" in deps
    assert "get_current_admin" not in deps, "普通用户也要能看到有哪些 agent"


def test_writes_are_admin_scoped():
    cases = [
        ("/agents", "POST"),
        ("/agents/{agent_id}", "PATCH"),
        ("/agents/{agent_id}", "DELETE"),
        ("/agents/{agent_id}/prompts", "POST"),
        ("/agents/{agent_id}/prompts/{version}/activate", "POST"),
    ]
    for path, method in cases:
        route = next(r for r in _all_routes() if r.path == path and method in r.methods)
        deps = _dependency_names(route)
        assert "get_current_admin" in deps, f"{method} {path} 必须是管理员接口"


def test_unauthenticated_agent_list_is_401():
    assert client.get("/agents").status_code == 401


def test_orm_tables_have_expected_columns():
    agent_cols = set(Agent.__table__.columns.keys())
    prompt_cols = set(AgentPrompt.__table__.columns.keys())
    assert {
        "agent_key",
        "platform",
        "model",
        "thinking",
        "tool_names_json",
        "active_prompt_version",
        "is_active",
    } <= agent_cols
    assert {"agent_id", "version", "system_prompt"} <= prompt_cols


def test_chat_request_accepts_agent_key():
    props = app.openapi()["components"]["schemas"]["ChatRequest"]["properties"]
    assert "agent_key" in props
