import asyncio
from types import SimpleNamespace

import pytest

from app.context import history_compactor as hc
from app.context import history as history_module
from app.session import service as session_service


class FakeModel:
    """记录收到的消息，返回固定摘要文本。"""

    model_name = "fake-model"

    def __init__(self, content: str = "这是 LLM 生成的摘要"):
        self.content = content
        self.messages = []

    async def ainvoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.content)


def row(
    rid: int, role: str, content: str = "", tool_name: str = "", is_summary: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid, role=role, content=content, tool_name=tool_name, is_summary=is_summary
    )


def setup_mocks(monkeypatch, rows, saved, summary=None):
    async def fake_get_session(_db, _sid, _uid):
        return object()

    async def fake_load_unsummarized_messages(_db, _sid):
        return [r for r in rows if not r.is_summary]

    async def fake_get_summary(_db, _sid):
        return summary

    async def fake_mark_summarized(_db, _sid, _uid, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(session_service, "get_session", fake_get_session)
    monkeypatch.setattr(session_service, "load_unsummarized_messages", fake_load_unsummarized_messages)
    monkeypatch.setattr(session_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(session_service, "mark_summarized", fake_mark_summarized)


def test_short_history_does_not_touch_db(monkeypatch):
    """不足 3 轮时直接返回，不调 LLM 也不打标。"""
    model = FakeModel()
    saved = {}
    setup_mocks(monkeypatch, [row(1, "user", "你好"), row(2, "assistant", "在的")], saved)

    asyncio.run(hc.compact_history(object(), 1, user_id=1, model=model))
    assert model.messages == []
    assert saved == {}


def test_compact_history_marks_old_messages_and_saves_summary(monkeypatch):
    """压缩后：旧轮次打 is_summary 标记（原文保留），摘要进独立表。"""
    model = FakeModel(content="LLM 摘要")
    rows = [
        row(1, "user", "旧问题1"),
        row(2, "assistant", "旧回答1"),
        row(3, "user", "旧问题2"),
        row(4, "assistant", "旧回答2"),
        row(5, "user", "最近问题"),
        row(6, "assistant", "", tool_name="web_search"),
        row(7, "tools", "搜索结果正文"),
        row(8, "user", "最后问题"),
        row(9, "assistant", "最后回答"),
    ]
    saved = {}
    setup_mocks(monkeypatch, rows, saved)

    asyncio.run(hc.compact_history(object(), 1, user_id=1, model=model))

    assert saved["summary"] == "LLM 摘要"
    assert saved["model"] == "fake-model"
    # 只有更早轮次（1-4）被打标，最近两轮（5-9）不动
    assert saved["message_ids"] == {1, 2, 3, 4}

    human = model.messages[1]
    assert "旧问题1" in human.content
    assert "旧问题2" in human.content
    assert "最近问题" not in human.content
    assert "搜索结果正文" not in human.content


def test_already_summarized_messages_are_skipped(monkeypatch):
    """已打 is_summary 的消息不再重复参与摘要。"""
    model = FakeModel()
    rows = [
        row(1, "user", "已摘要问题", is_summary=True),
        row(2, "assistant", "已摘要回答", is_summary=True),
        row(3, "user", "旧问题"),
        row(4, "assistant", "旧回答"),
        row(5, "user", "最近问题"),
        row(6, "assistant", "最近回答"),
    ]
    saved = {}
    setup_mocks(monkeypatch, rows, saved)

    asyncio.run(hc.compact_history(object(), 1, user_id=1, model=model))

    # 已摘要的 2 行被跳过，剩下只有 2 轮（3-4、5-6），不触发压缩
    assert model.messages == []
    assert saved == {}


def test_previous_summary_is_folded_in(monkeypatch):
    """已有摘要作为输入，生成新摘要后 upsert 覆盖。"""
    model = FakeModel(content="新摘要")
    rows = [
        row(1, "user", "旧问题1"),
        row(2, "assistant", "旧回答1"),
        row(3, "user", "旧问题2"),
        row(4, "assistant", "旧回答2"),
        row(5, "user", "最近问题"),
        row(6, "assistant", "最近回答"),
    ]
    saved = {}
    summary = SimpleNamespace(content="此前要点", model="old-model")
    setup_mocks(monkeypatch, rows, saved, summary)

    asyncio.run(hc.compact_history(object(), 1, user_id=1, model=model))

    human = model.messages[1]
    assert "此前摘要" in human.content
    assert "此前要点" in human.content
    assert saved["summary"] == "新摘要"


def test_missing_session_raises(monkeypatch):
    async def fake_get_session(_db, _sid, _uid):
        return None

    monkeypatch.setattr(session_service, "get_session", fake_get_session)
    with pytest.raises(LookupError):
        asyncio.run(hc.compact_history(object(), 1, user_id=1, model=FakeModel()))


def test_wrap_history_with_summary_uses_xml_blocks():
    """摘要与消息分别用 <message_summary> / <messages> 包裹，摘要不再是 SystemMessage。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages = [HumanMessage(content="你好"), AIMessage(content="你好呀")]
    out = history_module.wrap_history("用户偏好简洁回答", messages)

    assert len(out) == 1
    assert isinstance(out[0], HumanMessage)
    assert not isinstance(out[0], SystemMessage)
    assert out[0].content == (
        "<message_summary>\n用户偏好简洁回答\n</message_summary>\n\n"
        "<messages>\n用户：你好\n\n助手：你好呀\n</messages>"
    )


def test_wrap_history_without_summary_still_wraps_messages():
    """没有摘要时消息仍用 <messages> 包裹。"""
    from langchain_core.messages import AIMessage, HumanMessage

    messages = [HumanMessage(content="你好"), AIMessage(content="你好呀")]
    out = history_module.wrap_history("", messages)

    assert len(out) == 1
    assert out[0].content == "<messages>\n用户：你好\n\n助手：你好呀\n</messages>"
