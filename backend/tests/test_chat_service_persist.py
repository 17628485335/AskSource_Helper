"""stream_chat 的落库时机测试（不连 MySQL，也不发网络请求）

守的是「别把会话留在只有一半的状态」：客户端中途断开（router 的 keepalive 会 cancel
上游）或上游报错时，已经吐出来的字也要入库。只在正常遍历结束时写会留下一轮只有 user、
没有 assistant 的悬空记录，下一轮历史就是两条连着的 user。

session_service / AsyncSessionLocal / ChatManager 全部换成内存实现，
因此这里只验证编排时序，不碰真库。
"""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

import app.chat.service as chat_service
import auth.database


class _StubAgent:
    """先吐两段增量，然后一直挂着：模拟用户点「停止」/关页面那一刻的流"""

    platform = "deepseek"
    model_name = "deepseek-chat"

    def __init__(self, hang: asyncio.Event | None = None) -> None:
        self._hang = hang

    def effective_thinking(self, thinking):
        return False

    def descriptor(self, thinking):
        return {"platform": self.platform, "model": self.model_name, "thinking": False}

    async def stream(self, history, *, system_prompt=None, thinking=False):
        yield {"type": "token", "text": "前半段"}
        yield {"type": "token", "text": "，还在写"}
        if self._hang is not None:
            await self._hang.wait()  # 永不置位 → 消费端在这里被断开


class _QuickAgent(_StubAgent):
    """正常收尾：吐完就结束，用来验证 done 事件与「只落一次库」"""

    async def stream(self, history, *, system_prompt=None, thinking=False):
        yield {"type": "token", "text": "完整"}
        yield {"type": "token", "text": "回答"}


@pytest.fixture()
def recorded(monkeypatch):
    """把数据库会话与落库函数换成内存实现，返回写进去的 (role, content) 列表"""
    saved: list[tuple[str, str]] = []

    class _SessionCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_exc):
            return False

    async def fake_append(db, sid, uid, *, role, content, **_kw):
        saved.append((role, content))

    async def fake_get_session(db, sid, uid):
        return SimpleNamespace(id=sid)

    async def fake_load_history(db, sid, **_kw):
        return [HumanMessage(content="历史")]

    monkeypatch.setattr(auth.database, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(chat_service.session_service, "append_message", fake_append)
    monkeypatch.setattr(chat_service.session_service, "get_session", fake_get_session)
    monkeypatch.setattr(chat_service.session_service, "load_history", fake_load_history)
    return saved


def _use_agent(monkeypatch, agent):
    """让 stream_chat 挑到指定的 ModelAgent 替身（池本身不参与本测试）"""

    async def fake_get(_db):
        return SimpleNamespace(pick=lambda **_kw: agent)

    monkeypatch.setattr(chat_service.ChatManager, "get", staticmethod(fake_get))


def test_partial_answer_is_saved_when_client_disconnects(recorded, monkeypatch):
    """读到一半 aclose（等价于客户端断开）：已生成的字必须落库"""
    _use_agent(monkeypatch, _StubAgent(hang=asyncio.Event()))

    async def run():
        gen = chat_service.stream_chat(user_id=1, message="提问", session_id=7)
        events = []
        async for event in gen:
            events.append(event)
            if len(events) == 3:  # meta + 两条 delta，此时上游还挂着
                break
        await gen.aclose()
        return events

    events = asyncio.run(run())
    assert [e["type"] for e in events] == ["meta", "token", "token"]
    assert ("assistant", "前半段，还在写") in recorded, "断开时已生成的部分也要入库"


def test_full_answer_is_persisted_once(recorded, monkeypatch):
    """正常结束：落库一次，done 事件带回同一份内容，不能出现重复的 assistant 行"""
    _use_agent(monkeypatch, _QuickAgent())

    async def run():
        return [
            e
            async for e in chat_service.stream_chat(
                user_id=1, message="提问", session_id=7
            )
        ]

    events = asyncio.run(run())
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "完整回答"
    assert recorded == [("user", "提问"), ("assistant", "完整回答")]
