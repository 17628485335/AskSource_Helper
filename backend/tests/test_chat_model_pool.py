"""ChatManager 模型池的构建与挑选测试（不依赖 MySQL，也不发网络请求）

守住的是「一行 = 一个可对话的模型，一个模型 = 一份图」这套形状：同平台能有多行、
深度档位是逐轮参数而不是第二个实例，以及 pick() 的三级回落和报错文案。
build() 吃任意有同名属性的行对象，所以这里用 SimpleNamespace 顶替 ORM 行。
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool

from app.chat import ChatConfigError, ChatManager, ModelAgent
from app.chat import chat_manager as chat_manager_module
from app.chat.chat_manager import (
    DEFAULT_SYSTEM_PROMPT,
    LOCAL_TZ,
    compose_system_prompt,
    count_tool_calls_this_turn,
    date_line,
    filter_tools_by_call_limit,
    filter_tools_by_names,
)
from app.settings.llm import ReasoningChatOpenAI, _reasoning_delta, build_model


def row(
    platform: str,
    model: str,
    *,
    key: str = "sk-1",
    base: str = "",
    thinking: bool = False,
    active: bool = False,
) -> SimpleNamespace:
    """一行 llm_providers（字段名与 ORM 保持一致）"""
    return SimpleNamespace(
        platform=platform,
        default_model=model,
        api_key=key,
        base_url=base,
        supports_thinking=thinking,
        is_active=active,
        name="",
    )


@pytest.fixture()
def pool():
    """active 的支持思考模型 + 同平台第二个模型 + 另一平台 + 一条空模型 + 一条重复行"""
    return ChatManager.build(
        [
            row("siliconflow", "Org/Big", thinking=True, active=True),
            row("siliconflow", "Org/Fast"),
            row("deepseek", "deepseek-chat", key="sk-2"),
            row("deepseek", "  "),
            row("siliconflow", "Org/Big", key="sk-dup"),
        ]
    )


def test_build_one_agent_per_model(pool):
    """键里不再有 thinking：支持深度思考的模型也不多出一份实例"""
    assert set(pool.agents) == {
        ("siliconflow", "Org/Big"),
        ("siliconflow", "Org/Fast"),
        ("deepseek", "deepseek-chat"),
    }
    # 空模型行不构成可选项；重复行保留第一条（它带着原密钥）
    assert pool.agents[("siliconflow", "Org/Big")].api_key == "sk-1"


def test_thinking_capability_is_per_row(pool):
    big = pool.agents[("siliconflow", "Org/Big")]
    fast = pool.agents[("siliconflow", "Org/Fast")]
    # 支持深度的行才有可换的深度态模型，其余行压根不建
    assert big.supports_thinking and big.thinking_model is not None
    assert not fast.supports_thinking and fast.thinking_model is None
    # 没表态（None）与请求不支持的模型都不开深度：深度首字很慢，要求显式选择
    assert big.effective_thinking(None) is False
    assert big.effective_thinking(True) is True
    assert fast.effective_thinking(True) is False
    # meta 事件带的是本轮实际生效的档位，不是行配置
    assert big.descriptor(True)["thinking"] is True
    assert fast.descriptor(True)["thinking"] is False


def test_default_keys_follow_row_order(pool):
    # 全局默认 = active 行；键只是 (平台, 模型)
    assert pool.default_key == ("siliconflow", "Org/Big")
    assert set(pool.platform_default) == {"siliconflow", "deepseek"}


def test_pick_falls_back_model_platform_default(pool):
    assert pool.pick().model_name == "Org/Big"
    assert pool.pick(platform="deepseek").platform == "deepseek"
    assert pool.pick(platform="siliconflow", model="Org/Fast").api_key == "sk-1"
    # 只给模型名也能定位到所属平台
    assert pool.pick(model="Org/Fast").platform == "siliconflow"


def test_pick_reports_missing_model_or_platform(pool):
    with pytest.raises(ChatConfigError, match="未接入模型 Org/Nope"):
        pool.pick(platform="siliconflow", model="Org/Nope")
    with pytest.raises(ChatConfigError, match="还没有管理员配置的模型"):
        pool.pick(platform="bailian")


def test_broken_row_does_not_poison_the_pool():
    """一个坏配置只该废掉那个模型，不该让整池起不来"""
    mixed = ChatManager.build([row("nope", "x/y"), row("deepseek", "deepseek-chat")])
    assert len(mixed.agents) == 1 and len(mixed.errors) == 1
    assert mixed.default_key == ("deepseek", "deepseek-chat")

    all_bad = ChatManager.build([row("nope", "x/y")])
    with pytest.raises(ChatConfigError, match="全部构建失败"):
        all_bad.pick()


def test_empty_pool_points_to_admin():
    with pytest.raises(ChatConfigError, match="联系管理员"):
        ChatManager.build([]).pick()


def test_agent_graph_is_built_eagerly(pool):
    """图在构造时就编译好，不再需要懒构建与实例锁"""
    agent = pool.pick(platform="deepseek")
    assert agent.agent is not None and agent.chat_model is not None
    assert not hasattr(agent, "_lock")


def test_names_are_normalized_on_build_and_pick():
    """带空格的配置不能让「下拉里选得到、一发就报未接入」

    库里存的是历史脏数据（建池时 strip，但 /settings/models 一度返回原值），
    所以建池键与 pick() 入参两头都得归一。
    """
    padded = ChatManager.build([row("  deepseek ", "  deepseek-chat ", active=True)])
    assert set(padded.agents) == {("deepseek", "deepseek-chat")}
    assert padded.pick(platform="deepseek", model="  deepseek-chat ").model_name == "deepseek-chat"
    assert padded.pick(platform="", model="deepseek-chat").platform == "deepseek"


# ---------------- 工具：整池只取一次 ----------------


class _NoopTool(BaseTool):
    """建图时要拿到真的 BaseTool，用 SimpleNamespace 顶会被 create_agent 拒掉"""

    name: str = "noop"
    description: str = "测试用的空工具"

    def _run(self, query: str = "") -> str:  # type: ignore[override]
        return "ok"


def test_tools_are_loaded_once_for_the_whole_pool(monkeypatch):
    """工具在建池时取一次，每个 agent 直接用那份，不再逐模型各调一次注册表"""
    calls: list[int] = []

    def fake_get_tools(**_kw):
        calls.append(1)
        return [_NoopTool()]

    monkeypatch.setattr(chat_manager_module, "get_tools", fake_get_tools)
    built = ChatManager.build(
        [
            row("deepseek", "a", active=True),
            row("deepseek", "b"),
            row("siliconflow", "Org/Fast", thinking=True),
        ]
    )
    assert len(calls) == 1, "取工具的次数与模型数无关，整池就一次"
    assert len(built.tools) == 1
    # 每个 agent 用的是同一个工具实例（不是各自重新构造一份带状态的副本）
    for agent in built.agents.values():
        assert agent.tools[0] is built.tools[0]


def test_broken_tools_degrade_to_chat_only_not_kill_the_pool(monkeypatch):
    """工具实例化失败只该让整池退化成纯对话，不该让每个模型都建不起来

    逐项加载时，一个需要 db 的工具会让 N 行全失败、池为空，/chat 直接报
    「模型全部构建失败」，归因还指向管理员的配置。
    """

    def boom(**_kw):
        raise TypeError("Missing required argument: 'db'")

    monkeypatch.setattr(chat_manager_module, "get_tools", boom)
    built = ChatManager.build([row("deepseek", "deepseek-chat", active=True)])

    assert set(built.agents) == {("deepseek", "deepseek-chat")}
    assert built.errors == [] and built.tools == []
    assert "工具实例化失败" in built.tools_error
    assert built.pick().tools == []  # 图照常用，只是不带工具


def test_has_and_unavailable_reason_track_the_pool():
    """给 /settings/models 用的可用性标注：在表里不等于能聊"""
    mixed = ChatManager.build([row("deepseek", "good", active=True), row("nope", "broken")])
    assert mixed.has("deepseek", "good") is True
    assert mixed.has("nope", "broken") is False
    # 只给模型名时按任一平台查
    assert mixed.has("", "broken") is False
    assert "ValueError" in mixed.unavailable_reason("nope", "broken")


def test_cold_get_builds_the_pool_once(monkeypatch):
    """预热失败后两个并发请求同时走冷路径，只该建一次池

    load() 里的 `await db.scalars` 是挂起点，不锁就会各建一份，后建的覆盖先建的。
    """
    ChatManager.reset()
    builds = []

    async def fake_load(cls, _db):
        builds.append(1)
        await asyncio.sleep(0)  # 让另一个请求有机会插进来
        return cls.build([row("deepseek", "deepseek-chat", active=True)])

    monkeypatch.setattr(ChatManager, "load", classmethod(fake_load))

    async def run():
        return await asyncio.gather(ChatManager.get(None), ChatManager.get(None))

    try:
        first, second = asyncio.run(run())
        assert len(builds) == 1 and first is second
    finally:
        ChatManager.reset()


# ---------------- 一份图、两种档位 ----------------

_called: list[str] = []


class _SpyModel(BaseChatModel):
    """记录自己被调用过，用来验证深度档位换的是哪一份模型。

    新协议从 on_chat_model_stream 取正文，只实现 _generate 的桩不会产 stream 帧，
    所以这里两个都给（图在流式路径下先试 _stream，BaseChatModel 的默认实现会报
    NotImplementedError 并回落 _generate，但事件流里就没有 chunk 了）。
    """

    tag: str = "off"

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        _called.append(self.tag)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        _called.append(self.tag)
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))


def test_stream_swaps_model_per_request(monkeypatch):
    """stream(thinking=True) 走深度态那份模型，False 走快速态 —— 图始终只有一张"""

    def fake_build(platform: str, model: str, thinking: bool, **_kwargs):
        return _SpyModel(tag="on" if thinking else "off")

    monkeypatch.setattr(chat_manager_module, "build_model", fake_build)
    _called.clear()
    agent = ModelAgent("siliconflow", "Org/Big", supports_thinking=True, api_key="sk-1")
    graph = agent.agent  # 建图后不再更换

    async def ask(thinking: bool) -> str:
        events = [e async for e in agent.stream([HumanMessage(content="hi")], thinking=thinking)]
        return "".join(e["text"] for e in events if e["type"] == "token")

    assert asyncio.run(ask(False)) == "ok"
    assert asyncio.run(ask(True)) == "ok"
    assert agent.agent is graph
    assert _called == ["off", "on"]


def test_stream_ignores_thinking_when_unsupported(monkeypatch):
    """不支持深度思考的行：即使客户端硬要 True，也只会用快速态那份模型"""

    def fake_build(platform: str, model: str, thinking: bool, **_kwargs):
        return _SpyModel(tag="on" if thinking else "off")

    monkeypatch.setattr(chat_manager_module, "build_model", fake_build)
    _called.clear()
    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1")

    async def ask() -> None:
        async for _ in agent.stream([HumanMessage(content="hi")], thinking=True):
            pass

    asyncio.run(ask())
    assert _called == ["off"]


# ---------------- 历史里的 system 行 ----------------

_sent: list[list] = []


class _SpyMessagesModel(BaseChatModel):
    """把每次真的发出去的消息列表记下来，用来数 system 的条数与位置"""

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        _sent.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


def test_stream_drops_stored_system_messages(monkeypatch):
    """/sessions/{id}/messages 写过的 system 行不得再叠上本轮的 system

    两条 system、且一条不在头部，部分 OpenAI 兼容上游会直接 400，等于把这个会话永久卡死。
    """

    def fake_build(platform: str, model: str, thinking: bool, **_kwargs):
        return _SpyMessagesModel()

    monkeypatch.setattr(chat_manager_module, "build_model", fake_build)
    _sent.clear()
    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1")

    async def ask() -> None:
        history = [SystemMessage(content="用户自己写的旧提示"), HumanMessage(content="hi")]
        async for _ in agent.stream(history):
            pass

    asyncio.run(ask())
    sent = _sent[0]
    systems = [m for m in sent if isinstance(m, SystemMessage)]
    assert len(systems) == 1, "只该有本轮注入的那一条 system"
    # 注入时会拼上日期行（compose_system_prompt），只断言以默认提示词开头
    assert systems[0].content.startswith(DEFAULT_SYSTEM_PROMPT)
    assert sent[0] is systems[0], "system 必须在上下文头部"
    # 业务消息不能被误删
    assert [m.content for m in sent if not isinstance(m, SystemMessage)] == ["hi"]


# ---------------- 时效上下文与工具返回 ----------------


def test_date_line_uses_beijing_wall_clock():
    """UTC 晚上对应北京次日凌晨，差的就是那一天（模型会把「今天」算错一天）"""
    assert date_line(datetime(2026, 11, 25, 17, 30, tzinfo=timezone.utc)) == (
        "今天是 2026-11-26 周四（北京时间）。"
    )
    # 同一个 UTC 钟面再早一小时还在当天：跳日时刻得按北京墙钟算
    assert date_line(datetime(2026, 11, 25, 15, 59, tzinfo=timezone.utc)) == (
        "今天是 2026-11-25 周三（北京时间）。"
    )


def test_compose_prompt_appends_date_without_tool_hints():
    assert compose_system_prompt("你好", now=datetime(2026, 1, 1, tzinfo=LOCAL_TZ)) == (
        "你好\n\n今天是 2026-01-01 周四（北京时间）。"
    )
    # 工具不再触发额外的引用说明
    assert compose_system_prompt("你好", ["web_search", "read_url"]) == (
        compose_system_prompt("你好", ["noop"])
    )
    assert "[n]" not in compose_system_prompt("你好", ["web_search", "read_url"])
    # 传空串 = 本轮不带系统消息，不能被日期行救回去
    assert compose_system_prompt("", ["web_search"]) == ""
    assert compose_system_prompt("   \n", ["web_search"]) == ""


class _StubGraph:
    """只回放 astream_events 形状的事件字典（ModelAgent.stream 只吃 on_chat_model_stream/end 等协议源事件），
    顺带记下每轮的 messages 供断言注入"""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.states: list[dict] = []

    async def astream_events(self, state, **_kwargs):
        self.states.append(state)
        self.prompts.append(state["messages"][0].content)
        yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="ok")}}


def test_date_is_computed_per_turn_not_frozen_at_pool_build(monkeypatch):
    """模型池进程常驻：建池时算死日期，跳天之后所有回答的「今天」都是错的"""

    monkeypatch.setattr(chat_manager_module, "build_model", lambda *_a, **_k: _SpyMessagesModel())
    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1", tools=[])
    graph = _StubGraph()
    agent.agent = graph

    async def ask(day: str) -> None:
        monkeypatch.setattr(chat_manager_module, "date_line", lambda *_a, **_k: f"今天是 {day}（北京时间）。")
        async for _ in agent.stream([HumanMessage(content="hi")]):
            pass

    asyncio.run(ask("2020-01-01 周三"))
    asyncio.run(ask("2021-02-02 周二"))
    assert ["2020-01-01" in p for p in graph.prompts] == [True, False]
    assert "2021-02-02" in graph.prompts[1]
    assert graph.prompts[1].startswith(DEFAULT_SYSTEM_PROMPT)


def test_tool_whitelist_none_is_all_empty_is_none():
    tools = [SimpleNamespace(name="web_search"), SimpleNamespace(name="read_url")]
    assert [t.name for t in filter_tools_by_names(tools, None)] == ["web_search", "read_url"]
    assert filter_tools_by_names(tools, []) == []
    assert [t.name for t in filter_tools_by_names(tools, ["read_url"])] == ["read_url"]


def test_tool_call_limit_counts_only_current_turn_and_filters_exhausted_tools():
    """上一轮的历史不占额度；达到 max_calls 的工具从后续模型调用里摘掉"""
    old_turn = AIMessage(
        content="",
        tool_calls=[{"name": "web_search", "args": {}, "id": "old", "type": "tool_call"}],
    )
    current_turn = AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "web_search", "args": {}, "id": "c2", "type": "tool_call"},
            {"name": "read_url", "args": {}, "id": "c3", "type": "tool_call"},
        ],
    )
    messages = [
        HumanMessage(content="上一轮"),
        old_turn,
        ToolMessage(content="旧结果", tool_call_id="old"),
        HumanMessage(content="这一轮"),
        current_turn,
        ToolMessage(content="结果", tool_call_id="c1"),
    ]

    counts = count_tool_calls_this_turn(messages)
    assert counts == {"web_search": 2, "read_url": 1}

    tools = [SimpleNamespace(name="web_search"), SimpleNamespace(name="read_url")]
    kept = filter_tools_by_call_limit(tools, messages, {"web_search": 3, "read_url": 1})
    assert [t.name for t in kept] == ["web_search"]
    # 没写上限的工具不受影响
    assert [t.name for t in filter_tools_by_call_limit(tools, messages, {"web_search": 2})] == [
        "read_url"
    ]


def _tool_end(name: str, content: str, artifact: dict | None = None, call_id: str = "c") -> dict:
    msg = ToolMessage(content=content, tool_call_id=call_id, name=name)
    if artifact is not None:
        msg.artifact = artifact
    return {"event": "on_tool_end", "name": name, "data": {"output": msg}}


def _model_end_tool_calls(calls: list[dict]) -> dict:
    """on_chat_model_end 的新协议源：output 是装配好 tool_calls 的 AIMessage"""
    msg = AIMessage(
        content="",
        tool_calls=[{**c, "type": "tool_call"} for c in calls],
    )
    return {"event": "on_chat_model_end", "data": {"output": msg}}


def _model_start() -> dict:
    """on_chat_model_start：一次模型调用的开头，即一个新 segment 的边界"""
    return {"event": "on_chat_model_start", "data": {"input": {"messages": []}}}


class _ReplayGraph:
    """直接回放 astream_events(v2) 会看到的事件，绕开真的模型与图"""

    def __init__(self, events: list) -> None:
        self.events = events

    async def astream_events(self, _state, **_kwargs):
        for event in self.events:
            yield event


def test_tool_message_becomes_citations_instead_of_answer_text(monkeypatch):
    """工具的返回值不是助手的话：既不能当正文下发，引用又要能取出来"""
    monkeypatch.setattr(chat_manager_module, "build_model", lambda *_a, **_k: _SpyMessagesModel())
    ticks = iter([1.0, 1.0, 1.5, 2.25])  # 两次 start；两次 end（分别耗时 500 / 1250 ms）
    monkeypatch.setattr(
        chat_manager_module, "time", SimpleNamespace(perf_counter=lambda: next(ticks))
    )
    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1", tools=[])

    items = [{"index": 1, "url": "https://a.example", "title": "A"}]
    agent.agent = _ReplayGraph(
        [
            # tool_start 取自 on_chat_model_end 装配好的 tool_calls（带 call_id + 完整入参）
            _model_end_tool_calls([
                {"name": "web_search", "args": {"query": "q"}, "id": "call_w"},
                {"name": "noop", "args": {}, "id": "call_n"},
            ]),
            _tool_end("web_search", "检索「q」得到 1 条结果：[1] A", {"citations": items, "tools": "web_search"}, call_id="call_w"),
            _tool_end("noop", "工具啥也没返回", call_id="call_n"),
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="据 [1] ")}},
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="答案是 A。")}},
        ]
    )

    async def ask():
        return [e async for e in agent.stream([HumanMessage(content="hi")])]

    events = asyncio.run(ask())
    assert [e["type"] for e in events] == [
        "tool_start", "tool_start", "citations", "tool_end", "tool_end", "token", "token",
    ]
    # tool_start 携 call_id 与装配好的完整入参（model_end 一次报两个，都在最前）
    assert events[0] == {
        "type": "tool_start", "tool": "web_search", "call_id": "call_w", "input": {"query": "q"},
    }
    assert events[1] == {"type": "tool_start", "tool": "noop", "call_id": "call_n", "input": {}}
    assert events[2] == {"type": "citations", "tool": "web_search", "call_id": "call_w", "items": items}
    # tool_end 带同一个 call_id，前端据此把徽标从 running 翻成 done；duration_ms 是工具耗时
    assert events[3] == {
        "type": "tool_end", "tool": "web_search", "call_id": "call_w",
        "preview": "检索「q」得到 1 条结果：[1] A",
        "result": "检索「q」得到 1 条结果：[1] A", "duration_ms": 500,
    }
    assert events[4]["duration_ms"] == 1250
    body = "".join(e["text"] for e in events if e["type"] == "token")
    assert body == "据 [1] 答案是 A。", "工具原文混进正文就会落库"


def test_each_model_start_opens_a_new_segment(monkeypatch):
    """工具执行后模型再来一轮 = 新 segment，service 后续按它分段落库"""
    monkeypatch.setattr(chat_manager_module, "build_model", lambda *_a, **_k: _SpyMessagesModel())
    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1", tools=[])
    agent.agent = _ReplayGraph(
        [
            _model_start(),
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="先想调工具")}},
            _model_end_tool_calls([{"name": "noop", "args": {}, "id": "call_1"}]),
            _tool_end("noop", "工具结果", call_id="call_1"),
            _model_start(),
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="最终答案")}},
        ]
    )

    async def ask():
        return [e async for e in agent.stream([HumanMessage(content="hi")])]

    events = asyncio.run(ask())
    assert [e["type"] for e in events] == [
        "segment_start", "token", "tool_start", "tool_end", "segment_start", "token",
    ]
    assert [e["segment_id"] for e in events if e["type"] == "segment_start"] == [1, 2]


def test_citations_hint_survives_into_the_graph_input(monkeypatch):
    """挂了引用工具时，[n] 约定要真的随本轮 system 发出去"""

    monkeypatch.setattr(chat_manager_module, "build_model", lambda *_a, **_k: _SpyMessagesModel())

    class _SearchTool(BaseTool):
        name: str = "web_search"
        description: str = "占位"

        def _run(self, query: str = "") -> str:  # type: ignore[override]
            return "ok"

    agent = ModelAgent("deepseek", "deepseek-chat", api_key="sk-1", tools=[_SearchTool()])
    graph = _StubGraph()
    agent.agent = graph

    async def ask():
        return [e async for e in agent.stream([HumanMessage(content="hi")])]

    asyncio.run(ask())
    assert "[n]" in graph.states[0]["messages"][0].content


# ---------------- 思考过程（reasoning_content） ----------------


def test_reasoning_delta_only_picks_up_the_thinking_field():
    """取思考增量的容错：usage 帧、空 choices、没有该字段的普通模型都得安静返回空"""
    assert _reasoning_delta({"choices": [{"delta": {"reasoning_content": "想"}}]}) == "想"
    # beta 流会把真正的 chunk 包一层
    assert _reasoning_delta({"chunk": {"choices": [{"delta": {"reasoning_content": "b"}}]}}) == "b"
    assert _reasoning_delta({"choices": [{"delta": {"content": "白"}}]}) == ""
    assert _reasoning_delta({"choices": [{"delta": {"reasoning_content": None}}]}) == ""
    assert _reasoning_delta({"choices": []}) == ""
    assert _reasoning_delta({}) == ""
    assert _reasoning_delta(None) == ""


def test_model_keeps_reasoning_out_of_the_answer_text():
    """子类只补 reasoning_content，不得把思考混进正文（正文要落库、要喂下一轮）"""
    model = build_model("siliconflow", "Org/Big", True, api_key="sk-1")
    assert isinstance(model, ReasoningChatOpenAI)
    chunk = {
        "choices": [
            {
                "index": 0,
                "delta": {"reasoning_content": "先想", "content": "白"},
                "finish_reason": None,
            }
        ]
    }
    gen = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert gen.message.additional_kwargs["reasoning_content"] == "先想"
    assert gen.message.content == "白"


class _SpyStreamModel(BaseChatModel):
    """流式模型桩：先给两段思考，再给正文，看 stream() 怎么分发"""

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="答案"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先想"})
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", additional_kwargs={"reasoning_content": "再想"})
        )
        yield ChatGenerationChunk(message=AIMessageChunk(content="答案"))


def test_stream_emits_reasoning_as_separate_events(monkeypatch):
    """思考增量走 reasoning 事件，不混进 token：前端能展示，落库也不会带上"""
    monkeypatch.setattr(chat_manager_module, "build_model", lambda *_a, **_k: _SpyStreamModel())
    agent = ModelAgent("siliconflow", "Org/Big", supports_thinking=True, api_key="sk-1")

    async def ask():
        return [e async for e in agent.stream([HumanMessage(content="hi")], thinking=True)]

    events = asyncio.run(ask())
    assert [e["type"] for e in events] == ["segment_start", "reasoning", "reasoning", "token"]
    assert "".join(e["text"] for e in events if e["type"] == "reasoning") == "先想再想"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "答案"
