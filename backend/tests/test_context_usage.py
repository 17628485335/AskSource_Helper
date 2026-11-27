"""上下文用量计算：验证生效 system prompt 计入估算、API 快照优先。"""

import asyncio
from types import SimpleNamespace

from app.agents import service as agent_service
from app.context import usage as usage_module
from app.session import service as session_service


def test_estimated_usage_includes_active_system_prompt(monkeypatch):
    """没有 API 快照时，生效提示词的 token 要算进 used_tokens。"""
    prompt = "你是 AskSource 助手。" + "规则。" * 20

    async def fake_load_unsummarized_messages(_db, _sid):
        return []

    async def fake_get_summary(_db, _sid):
        return None

    async def fake_load_latest_usage_turn(_db, _sid):
        return None

    async def fake_resolve_agent(_db, key):
        assert key == "chat"
        return SimpleNamespace(system_prompt=prompt)

    monkeypatch.setattr(session_service, "load_unsummarized_messages", fake_load_unsummarized_messages)
    monkeypatch.setattr(session_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(session_service, "load_latest_usage_turn", fake_load_latest_usage_turn)
    monkeypatch.setattr(agent_service, "resolve_agent", fake_resolve_agent)

    out = asyncio.run(usage_module.get_context_usage(object(), 1, context_size=200000))

    from app.context.token_counter import estimate_text_tokens

    assert out["source"] == "estimated"
    assert out["used_tokens"] == estimate_text_tokens(prompt)
    assert out["message_count"] == 0


def test_api_snapshot_takes_priority(monkeypatch):
    """有 API 快照时用的是 last_* 之和，而不是估算值。"""
    async def fake_load_unsummarized_messages(_db, _sid):
        return []

    async def fake_get_summary(_db, _sid):
        return None

    async def fake_load_latest_usage_turn(_db, _sid):
        return SimpleNamespace(last_input_tokens=3000, last_output_tokens=500)

    async def fake_resolve_agent(_db, key):
        return SimpleNamespace(system_prompt="提示词")

    monkeypatch.setattr(session_service, "load_unsummarized_messages", fake_load_unsummarized_messages)
    monkeypatch.setattr(session_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(session_service, "load_latest_usage_turn", fake_load_latest_usage_turn)
    monkeypatch.setattr(agent_service, "resolve_agent", fake_resolve_agent)

    out = asyncio.run(usage_module.get_context_usage(object(), 1, context_size=200000))

    assert out["source"] == "api"
    assert out["used_tokens"] == 3500
    assert out["remaining_tokens"] == 196500


def test_invalidate_usage_snapshots_clears_last_tokens_only():
    turns = [
        SimpleNamespace(last_input_tokens=1200, last_output_tokens=300, input_tokens=9000),
        SimpleNamespace(last_input_tokens=800, last_output_tokens=120, input_tokens=4000),
    ]

    class FakeResult:
        def all(self):
            return turns

    class FakeDb:
        async def scalars(self, _query):
            return FakeResult()

    cleared = asyncio.run(session_service.invalidate_usage_snapshots(FakeDb(), 7))

    assert cleared == 2
    assert [(t.last_input_tokens, t.last_output_tokens) for t in turns] == [(0, 0), (0, 0)]
    assert [t.input_tokens for t in turns] == [9000, 4000]


def test_mark_summarized_invalidates_usage_snapshots(monkeypatch):
    called = {}

    async def fake_get_session(_db, _sid, _uid):
        return object()

    async def fake_get_summary(_db, _sid):
        return None

    async def fake_invalidate(_db, session_id):
        called["invalidate"] = session_id

    class FakeResult:
        def all(self):
            return []

    class FakeDb:
        async def scalars(self, _query):
            return FakeResult()

        def add(self, _obj):
            pass

        async def commit(self):
            called["commit"] = True

    monkeypatch.setattr(session_service, "get_session", fake_get_session)
    monkeypatch.setattr(session_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(session_service, "invalidate_usage_snapshots", fake_invalidate)

    asyncio.run(
        session_service.mark_summarized(
            FakeDb(), 7, 1, message_ids={1}, summary="摘要"
        )
    )

    assert called == {"invalidate": 7, "commit": True}
