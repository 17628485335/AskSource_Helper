"""token 计数模块测试：tiktoken 正常路径 + 不可用时的降级路径。"""

from langchain_core.messages import AIMessage, HumanMessage

import app.context.token_counter as token_counter


def test_empty_text_is_zero():
    assert token_counter.estimate_text_tokens("") == 0


def test_tiktoken_counts_chinese_and_english():
    """tiktoken 可用时按真实词表计数；中英文不再按字符数粗暴折半。"""
    if token_counter._get_encoding() is None:
        return
    text = "你好世界这是一段中文对话内容"
    assert token_counter.estimate_text_tokens(text) == 14
    english = "Hello world, this is a technical document about token counting."
    assert token_counter.estimate_text_tokens(english) == 12


def test_message_tokens_include_tool_calls():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "web_search", "args": {"q": "天气"}, "id": "call_1"}],
    )
    plain = AIMessage(content="")
    assert token_counter.estimate_message_tokens(message) > token_counter.estimate_message_tokens(plain)


def test_count_context_tokens_sums_messages():
    messages = [HumanMessage(content="你好"), AIMessage(content="在的")]
    assert token_counter.count_context_tokens(messages) == sum(
        token_counter.estimate_message_tokens(m) for m in messages
    )


def test_fallback_when_tiktoken_unavailable(monkeypatch):
    """tiktoken 不可用时降级到字符估算，不抛异常。"""
    monkeypatch.setattr(token_counter, "_get_encoding", lambda: None)

    assert token_counter.estimate_text_tokens("你好世界") == 4  # 中文一字一 token
    assert token_counter.estimate_text_tokens("abcd") == 1  # 英文四字符一 token
    assert token_counter.estimate_text_tokens("") == 0
