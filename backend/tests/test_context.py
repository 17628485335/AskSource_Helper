"""Phase 4 上下文段测试：路由权限、表结构、装配顺序（不连 MySQL）"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langchain_core.messages import SystemMessage

from app.context.assembler import build_skills_snapshot
from app.context.models import AgentContextBinding, AgentContextDoc, AgentMemory, UserContextDoc
from app.main import app

client = TestClient(app)


def _all_routes():
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None) or getattr(route, "routes", None)
        if inner is not None:
            stack.extend(list(inner.routes) if hasattr(inner, "routes") else inner)


def _dependency_names(route: APIRoute) -> set[str]:
    seen: set[str] = set()
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            seen.add(getattr(dep.call, "__name__", ""))
        stack.extend(dep.dependencies)
    return seen


def test_context_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/context/agent-bindings" in paths
    assert "/context/agent-docs" in paths
    assert "/context/user-docs" in paths


def test_agent_context_routes_require_admin():
    for path, method in [
        ("/context/agent-bindings", "GET"),
        ("/context/agent-bindings", "POST"),
        ("/context/agent-docs", "GET"),
        ("/context/agent-docs", "POST"),
    ]:
        route = next(r for r in _all_routes() if r.path == path and method in r.methods)
        assert "get_current_admin" in _dependency_names(route)


def test_user_context_routes_require_login():
    route = next(r for r in _all_routes() if r.path == "/context/user-docs" and "GET" in r.methods)
    deps = _dependency_names(route)
    assert "get_current_user" in deps
    assert "get_current_admin" not in deps


def test_unauthenticated_user_docs_is_401():
    assert client.get("/context/user-docs").status_code == 401


def test_list_agent_docs_uses_or_for_scoped_and_global():
    from sqlalchemy import select

    from app.context.service import list_agent_docs

    calls = []

    class FakeResult:
        def all(self):
            return []

    class FakeScalars:
        def all(self):
            return []

    class FakeDb:
        async def scalars(self, stmt):
            calls.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            return FakeScalars()

    asyncio.run(list_agent_docs(FakeDb(), 7))
    sql = calls[0]
    assert "agent_id = 7" in sql
    assert " OR " in sql
    assert "agent_id IS NULL" in sql
    assert " AND " not in sql


def test_list_agent_memories_scopes_global_and_user():
    from app.context.service import list_agent_memories

    calls = []

    class FakeScalars:
        def all(self):
            return []

    class FakeDb:
        async def scalars(self, stmt):
            calls.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            return FakeScalars()

    asyncio.run(list_agent_memories(FakeDb(), 7, user_id=3))
    sql = calls[0]
    assert "agent_id = 7" in sql
    assert "user_id = 0" in sql
    assert "user_id = 3" in sql
    assert " OR " in sql


def test_create_agent_memory_uses_payload_user_id():
    from app.context.schemas import AgentMemoryCreate
    from app.context.service import create_agent_memory

    class FakeDb:
        def add(self, _row):
            pass

        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    row = asyncio.run(
        create_agent_memory(FakeDb(), 7, AgentMemoryCreate(user_id=3, content="x"))
    )
    assert row.user_id == 3
    assert row.agent_id == 7


def test_orm_tables_have_expected_columns():
    assert {
        "agent_id", "key", "resolver", "ref_key", "enabled", "priority",
        "max_tokens", "trust_level", "trust_hint",
    } <= set(AgentContextBinding.__table__.columns.keys())
    assert {"agent_id", "key", "content", "version_hash"} <= set(
        AgentContextDoc.__table__.columns.keys()
    )
    assert {"user_id", "key", "content", "version_hash"} <= set(
        UserContextDoc.__table__.columns.keys()
    )
    assert {"agent_id", "user_id", "content", "enabled"} <= set(
        AgentMemory.__table__.columns.keys()
    )


def test_skills_snapshot_respects_whitelist():
    text = build_skills_snapshot(["web_search"])
    assert "web_search" in text
    assert "read_url" not in text
    assert build_skills_snapshot([]) == "本 Agent 未启用任何工具。"


def test_create_global_agent_doc_rejects_duplicate_key():
    from app.context import service as context_service
    from app.context.schemas import AgentContextDocCreate

    class FakeDb:
        async def scalar(self, _stmt):
            return 1

    payload = AgentContextDocCreate(key="agents_guide", content="x")
    with pytest.raises(context_service.ContextConflict):
        asyncio.run(context_service.create_agent_doc(FakeDb(), payload))


def test_astream_places_system_prompt_before_history():
    from langchain_core.messages import HumanMessage

    from app.chat.chat_manager import ModelAgent

    seen: dict[str, list] = {}

    class FakeCompiled:
        async def astream_events(self, payload, *, version=None, context=None):
            seen["messages"] = payload["messages"]
            seen["context"] = context
            if False:  # pragma: no cover - 保持 async generator 形状
                yield {}

    agent = ModelAgent.__new__(ModelAgent)
    agent.agent = FakeCompiled()
    agent.system_prompt = "SYS"
    agent.tools = []
    agent.thinking_model = None
    agent.supports_thinking = False

    stale_system = SystemMessage(content="OLD SYSTEM")
    human = HumanMessage(content="hi")

    async def collect():
        return [
            event
            async for event in agent.astream(
                [stale_system, human],
                system_prompt="SYS",
            )
        ]

    assert asyncio.run(collect()) == []
    messages = seen["messages"]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert "SYS" in messages[0].content
    assert messages[1] is human


def test_generate_route_registered_and_admin_only():
    assert "/context/generate" in app.openapi()["paths"]
    route = next(
        r for r in _all_routes() if r.path == "/context/generate" and "POST" in r.methods
    )
    assert "get_current_admin" in _dependency_names(route)


def test_generate_context_content_uses_kind_prompt_and_cleans_fence():
    from app.context import generator

    seen: dict[str, list] = {}

    class FakeModel:
        async def ainvoke(self, messages):
            seen["messages"] = messages
            return SimpleNamespace(content="```text\n- 简洁直接\n- 不编造事实\n```")

    content = asyncio.run(
        generator.generate_context_content(
            FakeModel(), "soul", current="旧内容", hint="更短", variant=1
        )
    )
    assert content == "- 简洁直接\n- 不编造事实"
    system, human = seen["messages"]
    assert isinstance(system, SystemMessage)
    assert "性格" in system.content
    assert "旧内容" in human.content
    assert "更短" in human.content
    assert "第 2 次生成" in human.content
