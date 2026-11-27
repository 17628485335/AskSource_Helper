"""会话接口契约测试（不依赖 MySQL）：防止端点函数与模块别名同名导致调用打到自身。"""

import asyncio
from types import SimpleNamespace

import app.session.router as session_router


def test_context_usage_endpoint_calls_service(monkeypatch):
    async def fake_owned_session(db, session_id, user_id):
        return None

    called = {}

    async def fake_get_context_usage(db, session_id, *, context_size):
        called["args"] = (session_id, context_size)
        return {
            "used_tokens": 120,
            "context_size": context_size,
            "remaining_tokens": context_size - 120,
            "usage_ratio": 0.0006,
            "message_count": 2,
            "summary_chars": 0,
            "source": "estimated",
        }

    monkeypatch.setattr(session_router, "_owned_session", fake_owned_session)
    monkeypatch.setattr(
        session_router.context_usage_service, "get_context_usage", fake_get_context_usage
    )

    out = asyncio.run(
        session_router.context_usage(
            session_id=7,
            context_size=200000,
            current_user=SimpleNamespace(id=1),
            db=object(),
        )
    )

    assert called["args"] == (7, 200000)
    assert out.used_tokens == 120
    assert out.context_size == 200000


def test_compact_endpoint_calls_compactor_and_returns_usage(monkeypatch):
    session = SimpleNamespace(id=7, platform="deepseek", model="deepseek-chat")
    called = {}

    async def fake_owned_session(_db, _sid, _user_id):
        return session

    class FakePool:
        def pick(self, *, platform, model):
            called["pick"] = (platform, model)
            return SimpleNamespace(chat_model="summary-model")

    class FakeChatManager:
        @staticmethod
        async def get(_db):
            return FakePool()

    async def fake_compact_history(_db, session_id, *, user_id, model):
        called["compact"] = (session_id, user_id, model)

    async def fake_invalidate(_db, session_id):
        called["invalidate"] = session_id

    class FakeDb:
        async def commit(self):
            called["commit"] = True

    async def fake_get_context_usage(_db, session_id, *, context_size):
        called["usage"] = (session_id, context_size)
        return {
            "used_tokens": 90,
            "context_size": context_size,
            "remaining_tokens": context_size - 90,
            "usage_ratio": 90 / context_size,
            "message_count": 3,
            "summary_chars": 88,
            "source": "estimated",
        }

    monkeypatch.setattr(session_router, "_owned_session", fake_owned_session)
    monkeypatch.setattr(session_router, "ChatManager", FakeChatManager)
    monkeypatch.setattr(session_router, "compact_history_service", fake_compact_history)
    monkeypatch.setattr(session_router.service, "invalidate_usage_snapshots", fake_invalidate)
    monkeypatch.setattr(
        session_router.context_usage_service, "get_context_usage", fake_get_context_usage
    )

    out = asyncio.run(
        session_router.compact_history(
            session_id=7,
            context_size=123456,
            current_user=SimpleNamespace(id=1),
            db=FakeDb(),
        )
    )

    assert called["pick"] == ("deepseek", "deepseek-chat")
    assert called["compact"] == (7, 1, "summary-model")
    assert called["invalidate"] == 7
    assert called["commit"] is True
    assert called["usage"] == (7, 123456)
    assert out.summary_chars == 88
    assert out.context_size == 123456
