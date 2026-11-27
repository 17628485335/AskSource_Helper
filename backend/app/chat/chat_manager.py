"""ChatManager：常驻的模型池；ModelAgent：单个模型的模型态与「问模型」

设计要点：
- 一行 llm_providers = 一个可对话的模型（平台 + 模型 + 该行自己的密钥/端点/思考支持），
  所以同一个平台能接多个模型，池里就是多个 agent，不需要新表也不需要新列。
- ChatManager 初始化时把配置里的每个模型各实例化一份 agent（一张图）。深度思考不再多一份
  实例：构造时顺带备好 on/off 两个模型（build_model 不建连不发请求，很轻），
  请求路径只挑不建 —— /chat 走 pick() 拿现成实例，thinking 由 stream() 逐轮传入，
  图里的中间件在真正调模型前把它换成深度态那份。
- 因此 llm_providers.supports_thinking 只决定「有没有深度态那份可换」，前端据此
  决定是否展示 快速/深度 选择（/settings/models 会把该字段一并返回）。
- 深度档的思考过程（上游 delta 里的 reasoning_content）以 reasoning 事件单独下发，
  不进正文也不落库：langchain-openai 明确不提取这个字段，不自己接的话深度档在
  前端就只剩干等，看起来和快速档一模一样。
- 工具的返回值（ToolMessage）既不是助手的话也不是正文，必须单独接住：
  不接的话正文提取会把整段搜索结果当成 token 发给前端并落库。
  stream() 只从 on_chat_model_stream 取正文；工具结果从 on_tool_end 取出，
  截断版作 preview 推前端、完整版作 result 交给 service 按 segment 落库。
- /settings/models 同时用 has() 标出该行是否真的建进了池（available）：列表读表、
  能不能聊取决于池，一行构建失败时它仍留在表里，不标注就会让前端选到一个必报错的模型。
- 构建时机只有两个：启动 lifespan 预热，以及管理员保存配置后 reload。因此不再有按
  「密钥/端点指纹」的实例缓存（原 _registry）：配置变了就整池重建，不靠指纹命中新实例。
- 单个 ModelAgent 的图在 initialize() 里同步建好，建池段（build）内部没有 await，不会留下
  半态实例。冷路径 get() 另有一把 loop 级锁：预热失败时两个并发请求可能同时进来，各建
  一份功能等价但纯属浪费的池，加锁只为避免那次重复构建（锁按事件循环重建，因为测试里
  会有多个 asyncio.run，跨 loop 复用同一个 Lock 会直接 RuntimeError）。
- _instance 是**进程级**的：多 worker 部署（uvicorn --workers N / gunicorn）时，管理员保存
  配置只会重建收到该请求的那个进程，其余进程仍拿着旧密钥直到重启。当前启动脚本是单进程
  + --reload，所以还不是问题；改成多进程部署要先加跨进程失效通知。
- 导入本模块不构建任何东西（不读库、不读 .env、不编译图）：alembic 迁库、pytest 收集、
  一次性脚本都会 import 到这里，实例在 ChatManager.build()/load() 时才建。
- 单行构建失败（未知平台、缺密钥、上游不认参数）只跳过那个模型并记进 errors，
  不让整池失败——一个坏配置不该拖垮其它可用模型。
- 实例不持有用户状态（user_id / session_id 全走参数），所以同一份能被不同用户复用。
  也因此流式过程中的临时状态（如已播报的工具名）必须放在生成器局部，不能挂到 self 上。
- 图里不绑定 system_prompt：系统提示词由 stream() 每轮动态注入，因此换提示词不需要重新
  编译，同一张缓存图能服务不同提示词；self.system_prompt 只是默认值。
- 工具注册表整池只取一次（ChatManager.build 里调 load_tools 并存到 self.tools），
  再作为参数传给每个 ModelAgent 直接建图。放到池级不只是为了少调几次：工具实例化
  失败属于代码问题而不是某一行的配置问题，逐项加载会让每个 ModelAgent 构造失败、
  一个坏工具拖垮整池；池级加载只会退化成「所有模型都不带工具」的纯对话。
- 具体工具写在 app/tools/（一个工具一个文件，按功能命名不带 _tool 后缀），
  导入该包即完成注册（见上方 import app.tools）；注册表在 app/graph/tools.py。
- 分层：ModelAgent 只管模型态与「问模型」——  stream() 直接消费 astream_events(v2)，
  用 graph.stream_protocol 的 ev_* 工厂产出 segment_start/token/reasoning/tool_start/tool_end/citations；
  会话归属、消息落库、取历史、meta/done/error 编排全部在 service.stream_chat()。
  那边分三段各自开关数据库会话（一次流式回答可能挂数十秒，全程持有请求级 db 会话
  会长时间占用连接池连接，并发稍高就耗尽。实测 FastAPI 注入的 db 在流式期间仍存活，
  所以这是资源占用问题，不是 correctness 问题。）
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 导入 app.tools 这个包 = 注册全部内置工具（各模块的 @register_tool 在导入期执行）。
# 只调 get_tools() 不会触发注册，漏掉这行的症状是「工具默默消失了」且不报错。
import app.tools  # noqa: F401
from app.graph import get_tool_spec, get_tools, tool_is_available
from app.graph.stream_protocol import (
    ev_citations,
    ev_reasoning,
    ev_segment_start,
    ev_token,
    ev_usage,
    ev_tool_end,
    ev_tool_start,
)
from app.prompt import build_system_prompt, date_line
from app.prompt import LOCAL_TZ as LOCAL_TZ  # noqa: F401  兼容测试导入
from app.settings.llm import build_model, get_llm_settings
from app.settings.models import LlmProvider
from app.tools.citations import extract_citations

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "你是 AskSource 助手。回答要简洁、直接；"
    "需要外部信息或执行操作时优先调用已提供的工具，不要编造结果。"
    "引用只在正文里用 [n] 标注，不要在末尾另列“参考来源”清单，界面会单独展示。"
)

# tool_end.preview 的截断长度：够前端 tooltip/展开区用，又不会把整页搜索原文推过网络
PREVIEW_CHARS = 400


def _text_of(content: Any) -> str:
    """消息 content 容错取值：str 或分块 list（推理模型的多模态形状）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


# 历史消息最多占上下文窗口的比例：其余留给系统提示、工具定义和本轮输出
HISTORY_BUDGET_RATIO = 0.6


def _drop_orphan_tool_messages(messages: list[Any]) -> list[Any]:
    """裁掉没有对应 tool_calls 的 ToolMessage，避免上游报「tool 结果没有调用」"""
    ids: set[str] = set()
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            cid = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            if cid:
                ids.add(cid)
    return [
        m
        for m in messages
        if not isinstance(m, ToolMessage) or getattr(m, "tool_call_id", "") in ids
    ]


def _trim_history(messages: Sequence[Any], context_size: int) -> list[Any]:
    """按模型上下文窗口裁剪历史：从最新往前保留，超预算就丢弃更早的轮次。

    这里用字符数/2 做保守粗估：只用于裁剪，刻意不追求与计费口径一致
    （精确计数在 app.context.token_counter，各家端点分词器不同，粗估更稳）。
    始终至少保留最后一条消息，避免裁成空历史；孤立的工具结果会被一并剔除。
    """
    budget = max(1024, int(context_size * HISTORY_BUDGET_RATIO))
    kept: list[Any] = []
    used = 0
    for msg in reversed(list(messages)):
        cost = max(1, len(_text_of(getattr(msg, "content", ""))) // 2)
        if kept and used + cost > budget:
            break
        kept.append(msg)
        used += cost
    return _drop_orphan_tool_messages(list(reversed(kept)))


def _result_of(output: Any) -> str:
    """工具完整结果：ToolMessage 取 content，dict 取字符串化，其余 str 兜底"""
    if isinstance(output, ToolMessage):
        text = _text_of(output.content)
    elif isinstance(output, dict):
        text = next(
            (_text_of(v.content) for v in output.values() if isinstance(v, ToolMessage)),
            str(output),
        )
    else:
        text = str(output)
    return text.strip()


def _preview_of(output: Any) -> str:
    """工具结果的展示摘要：完整结果截到 PREVIEW_CHARS，供前端 tooltip/展开区用"""
    return _result_of(output)[:PREVIEW_CHARS]


def _tool_name(tool: Any) -> str:
    """工具实例 / dict 形式工具声明的名字"""
    if isinstance(tool, dict):
        return str(tool.get("name") or "")
    return str(getattr(tool, "name", "") or "")


def filter_tools_by_names(tools: Sequence[Any], names: Sequence[str] | None) -> list[Any]:
    """按 agent 配置的白名单过滤工具；None=全部，[]=一个都不给模型"""
    if names is None:
        return list(tools)
    allowed = set(names)
    return [tool for tool in tools if _tool_name(tool) in allowed]


def count_tool_calls_this_turn(messages: Sequence[Any]) -> dict[str, int]:
    """数本轮（最后一条 HumanMessage 之后）每种工具已被调用几次。

    只看 tool_calls 声明，不依赖 ToolMessage：模型发出第 N 次调用的那一刻，
    middleware 就要据此决定是否还把该工具开放给它。
    """
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            start = i + 1
            break

    counts: dict[str, int] = {}
    for message in messages[start:]:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name", "") if isinstance(call, dict) else getattr(call, "name", "")
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def filter_tools_by_call_limit(
    tools: Sequence[Any], messages: Sequence[Any], limits: dict[str, int]
) -> list[Any]:
    """已达 max_calls 的工具从本轮后续模型调用里摘掉，limit<=0 视为不限制。"""
    if not limits:
        return list(tools)
    used = count_tool_calls_this_turn(messages)
    return [
        tool
        for tool in tools
        if not (
            (limit := limits.get(_tool_name(tool), 0)) > 0
            and used.get(_tool_name(tool), 0) >= limit
        )
    ]


def compose_system_prompt(prompt: str, *, now: datetime | None = None) -> str:
    """兼容旧调用；实际拼装逻辑在 app.prompt.build_system_prompt。"""
    return build_system_prompt(prompt, now=now, date_line_fn=date_line)


# 池里的索引：(平台, 模型)。一个模型一份图，思考态不在键里
ModelPair = tuple[str, str]


class ChatConfigError(RuntimeError):
    """没有可用的模型配置（管理员尚未接入密钥等），由接口转成可读错误"""


def load_tools() -> list[Any]:
    """取全部就绪的工具体实例，供整池共用；把「工具需要运行时依赖」这类错说清楚。

    池是无用户上下文的全局实例，建池时只能拿无参单例（get_tools() 不传 kwargs）。
    一旦有人注册了构造时需要 db / api_key / user_id 的 BaseTool，这里会报错
    —— 不加这层包装就只剩一句 pydantic 校验失败，表面症状是「工具默默消失了」，
    很难归因到工具自己的构造签名。

    工具自己声明的前置条件不满足（实现了 available() 且返回 False，如缺外部密钥）
    则跳过该工具而不是报错：模型看不到它就不会去调。这类跳过只记 warning，
    不能升成 ChatConfigError —— 没接搜索不影响纯对话可用，拦住建池代价太大。
    """
    try:
        tools = get_tools()
    except Exception as exc:
        raise RuntimeError(
            f"工具实例化失败：{exc}。模型池按无参单例取工具，"
            "需要运行时依赖（db / api_key / user_id）的工具请改成从调用上下文里取"
        ) from exc

    ready: list[Any] = []
    for tool in tools:
        if tool_is_available(tool):
            ready.append(tool)
        else:
            logger.warning("工具 %s 前置条件未满足（常见于未配置外部密钥），本次不挂进模型图", tool.name)
    return ready


class ModelAgent:
    """一个模型的 chat 模型、工具与编译好的 ReAct 图，并对外提供流式对话

    一个模型只有一份图：快速/深度靠 stream() 传入的 thinking 在调用前换模型，
    而不是编译两张图。
    """

    def __init__(
        self,
        platform: str,
        model: str,
        *,
        supports_thinking: bool = False,
        context_size: int = 200000,
        api_key: str = "",
        base_url: str = "",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        tools: Sequence[Any] | None = None,
    ) -> None:
        self.platform = platform
        self.model_name = model
        self.supports_thinking = supports_thinking
        self.context_size = context_size
        self.api_key = api_key
        self.base_url = base_url
        self.system_prompt = system_prompt
        # 工具列表由 ChatManager 整池取一次后传进来；单独实例化（测试、脚本）时才现取。
        # 判的是 is None 而不是真值：空列表是「池里确实没工具」的合法结论，不该再加载一次。
        self.tools: Sequence[Any] = list(tools) if tools is not None else load_tools()

        # 由 initialize() 填充：快速态模型、深度态模型（不支持时为 None）、编译好的图
        self.chat_model: Any = None
        self.thinking_model: Any = None
        self.agent: Any = None

        self.initialize()

    # ---------------- 初始化 ----------------

    def initialize(self) -> "ModelAgent":
        """从 settings/llm.py 构建模型，并同步编译 ReAct 图。

        两种思考态只是两个模型实例（构造不建连接、不发请求），图仍然只有一张；
        不支持深度思考的行连深度态那份都不建。
        工具不在这里取：整池共用 self.tools（由 ChatManager 传入），这里只管模型与图。
        """
        self.chat_model = build_model(
            self.platform,
            self.model_name,
            False,
            api_key=self.api_key,
            base_url=self.base_url,
        )
        self.thinking_model = (
            build_model(
                self.platform,
                self.model_name,
                True,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            if self.supports_thinking
            else None
        )
        self.agent = self._build_agent()
        return self

    def _build_agent(self) -> Any:
        """编译并返回 ReAct 图；仅类内部调用（initialize）。

        这里刻意不传 create_agent 的 system_prompt：提示词属于「这一轮怎么问」而不是
        「这个配置长什么样」，交给 stream() 逐轮注入，图才是纯配置态的产物，
        可以跨提示词复用。

        middleware 是「一份图服务两种思考态」的关键：图绑的是快速态模型，
        每轮真正调模型前由它按 runtime.context 里的 thinking 换成深度态那份
        （request.override 只改本次调用，不会污染实例上的图）。同一个 middleware
        还按工具注册时的 max_calls 摘掉本轮已用尽的工具，避免模型反复调用。

        不再需要原来的双重校验锁：图在这里同步建好，调用链（ChatManager.build）
        从查库结果到建图之间没有 await，同一个事件循环线程内不会被打断，
        不存在两个请求并发懒构建同一实例的场景。
        """
        from langchain.agents import create_agent
        from langchain.agents.middleware import wrap_model_call

        tool_limits: dict[str, int] = {}
        for tool in self.tools:
            name = _tool_name(tool)
            spec = get_tool_spec(name)
            if spec is not None and spec.max_calls > 0:
                tool_limits[name] = spec.max_calls

        @wrap_model_call
        async def select_thinking(request: Any, handler: Any) -> Any:
            next_request = request
            runtime_context = request.runtime.context if request.runtime is not None else None
            context = runtime_context if isinstance(runtime_context, Mapping) else {}
            thinking = bool(context.get("thinking"))
            if thinking and self.thinking_model is not None:
                next_request = next_request.override(model=self.thinking_model)

            tool_names = context.get("tool_names")
            current_tools = list(next_request.tools or [])
            if tool_names is not None or tool_limits:
                allowed = filter_tools_by_names(current_tools, tool_names)
                if tool_limits:
                    allowed = filter_tools_by_call_limit(
                        allowed, next_request.messages, tool_limits
                    )
                if allowed != current_tools:
                    next_request = next_request.override(tools=allowed)

            return await handler(next_request)

        return create_agent(
            model=self.chat_model,
            tools=self.tools,
            middleware=[select_thinking],
            context_schema=dict,
        )

    def effective_thinking(self, thinking: bool | None) -> bool:
        """本轮到底会不会开深度：模型不支持时一律 False（前端同样会把档位选择藏掉），
        传 None（客户端没表态）也不开 —— 深度比较慢，要求显式选择"""
        return bool(thinking) and self.supports_thinking

    def descriptor(self, thinking: bool = False) -> dict[str, Any]:
        """meta 事件里回给前端的模型信息（thinking 为本轮实际生效的档位）"""
        return {
            "platform": self.platform,
            "model": self.model_name,
            "thinking": self.effective_thinking(thinking),
        }

    def __repr__(self) -> str:
        return (
            f"<ModelAgent {self.platform}/{self.model_name} "
            f"supports_thinking={self.supports_thinking} tools={len(self.tools)}>"
        )

    # ---------------- 流式对话 ----------------

    async def astream(
        self,
        history: Sequence[Any],
        *,
        system_prompt: str | None = None,
        thinking: bool = False,
        tool_names: Sequence[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """只发起一次 astream_events(v2)，把图事件逐个翻译成协议事件：
        产出 segment_start* / token* / reasoning* / tool_start* / tool_end* / citations*。

        事件由 graph.stream_protocol 的 ev_* 工厂构造（字段名即前端契约）；本方法只负责
        「从 astream_events 的哪个事件、取哪个字段」，映射表见 stream_protocol 模块头。

        on_chat_model_start 是分段边界：一次流式回答里模型可能被调用多轮（工具执行后再来一轮），
        每轮开一个 segment，segment_id 从 1 递增。service 后续按 segment 分段落库。

        不碰数据库、不管会话与落库（那些在 service.stream_chat()），异常也原样抛出，
        由调用方转成 error 事件。

        thinking 走 context 交给图里的中间件：True 且该行支持深度思考时才换成深度态模型
        （实测 astream_events 的 context kwarg 原样到达 request.runtime.context）。
        tool_names 同理：None=模型池全部工具，[]=禁用所有工具，列表=只给白名单。

        reasoning 是思考增量（只在深度档出现），来自 ReasoningChatOpenAI 接住的
        reasoning_content，与正文 token 分事件下发，不进回答文本也不落库。

        citations 是工具返回的结构化引用（来自 on_tool_end 的 ToolMessage.artifact），
        只转发给前端；正文里的 [n] 与卡片上的 n 同号，因为编号由工具从图状态里
        接着本轮已用过的往下编。工具调用本身（参数 / call_id / 完整结果 / 耗时）
        由 service 从 tool_start / tool_end 收集，独立落到 chat_tool_calls 表。

        system_prompt 省略时回落到 self.system_prompt，传空串表示本轮不带系统消息。
        调用方传入的是管理端已拼好的完整提示词（含 <time> 日期），这里直接使用，
        不再二次拼装、也不改写日期。
        图里没有系统消息，所以每轮把它置于历史最前 —— 上游要求 system 在上下文头部。
        历史里已有的 system 行会被丢掉：/sessions/{id}/messages 允许写 system 角色，
        留着就是两条 system 且一条不在头部，部分 OpenAI 兼容上游会直接 400。

        announced / pending 必须是生成器局部状态：同一个实例会被并发请求复用，
        挂到 self 上会让后一个请求看不到前一个请求播报过的工具调用、也算错耗时。
        pending 的键取 call_id（并行同名调用才能各算一次），个别上游不返回 id 时回退工具名；
        值是本次调用待消费的中间参数（目前是 started_at），后续要带别的量直接往里加。
        """
        announced: set[str] = set()
        pending: dict[str, dict[str, Any]] = {}
        segment_id = 0
        prompt = self.system_prompt if system_prompt is None else system_prompt
        turns = [m for m in history if not isinstance(m, SystemMessage)]
        turns = _trim_history(turns, getattr(self, "context_size", 200000))
        head = [SystemMessage(content=prompt)] if prompt else []
        messages = [*head, *turns]
        async for ev in self.agent.astream_events(
            {"messages": messages},
            version="v2",
            context={
                "thinking": self.effective_thinking(thinking),
                "tool_names": list(tool_names) if tool_names is not None else None,
            },
        ):
            kind = ev["event"]

            if kind == "on_chat_model_start":
                # 每次模型起一轮就是一个新 segment（工具执行后模型再起一轮也会命中这里）
                segment_id += 1
                yield ev_segment_start(segment_id)

            elif kind == "on_chat_model_stream":
                chunk = (ev.get("data") or {}).get("chunk")
                if not isinstance(chunk, AIMessageChunk):
                    continue
                # 思考增量：由 settings.llm.ReasoningChatOpenAI 从 delta 里接住，父类会直接丢掉
                reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    yield ev_reasoning(reasoning)
                text = _text_of(chunk.content)
                if text:
                    yield ev_token(text)

            elif kind == "on_chat_model_end":
                # 工具调用到此已装配成 {name, args, id}：call_id 与完整入参只有此刻同时齐备
                # （模型流里的 tool_call_chunks 把 args 切成碎片、on_tool_start 又没有 tool_call_id），
                # 故 tool_start 从这里发。工具执行紧贴在本事件之后，徽标不会因此迟亮。
                out = (ev.get("data") or {}).get("output")
                # usage_metadata 也是此刻才齐备（流式 chunk 的 usage 已由 langchain 聚合）；
                # 上游不返回时为空，service 会回退到估算，不把它当错误。
                usage = getattr(out, "usage_metadata", None)
                if usage:
                    yield ev_usage(usage, segment_id=segment_id)
                for call in getattr(out, "tool_calls", None) or []:
                    name = call.get("name") or ""
                    call_id = call.get("id") or ""
                    key = call_id or name
                    if key and key not in announced:
                        announced.add(key)
                        pending[key] = {
                            "started_at": time.perf_counter(),
                            "name": name,
                            "call_id": call_id,
                        }
                        yield ev_tool_start(name, call_id, call.get("args"))

            elif kind == "on_tool_end":
                name = ev.get("name") or ""
                output = (ev.get("data") or {}).get("output")
                # tool_call_id 回指 on_chat_model_end 播报过的那次调用，前端据此配对翻状态
                call_id = getattr(output, "tool_call_id", "") or ""
                # 先算耗时再发事件：citations/tool_end 的 yield 会等下游消费，不能算进工具执行时间
                state = pending.pop(call_id or name, None)
                if state is None and call_id:
                    state = pending.pop(name, None)
                started_at = state.pop("started_at", None) if state else None
                duration_ms = None if started_at is None else round((time.perf_counter() - started_at) * 1000)
                # 正文只从 on_chat_model_stream 取，工具原文不会泄进正文（这里不涉及防泄漏）；
                # 这个 isinstance 纯粹是防御性：本项目工具恒回 ToolMessage（实测），但 langchain
                # 不保证这一点——工具返回 Command（state 更新 / interrupt / 子图路由）等非消息时，
                # artifact 只在 ToolMessage 上，取不到就跳过，别把非消息喂给 extract_citations。
                # citations 先于 tool_end 发，前端收到徽标「完成」时来源卡片已在路上
                if isinstance(output, ToolMessage):
                    items = extract_citations(output)
                    if items:
                        yield ev_citations(name, items, call_id)
                yield ev_tool_end(
                    name,
                    _preview_of(output),
                    call_id,
                    duration_ms,
                    result=_result_of(output),
                )

    # 兼容既有调用方与测试；实现以 astream 为准
    stream = astream


class ChatManager:
    """模型池：启动预热全部模型 agent，管理员改配置后重建，请求只做挑选"""

    _instance: "ChatManager | None" = None
    # 冷路径建池互斥：按当前事件循环持有（_build_lock），reset() 一并丢弃
    _lock: "asyncio.Lock | None" = None
    _lock_loop: "asyncio.AbstractEventLoop | None" = None

    def __init__(
        self,
        agents: dict[ModelPair, ModelAgent],
        *,
        platform_default: dict[str, ModelPair],
        default_key: ModelPair | None = None,
        errors: list[str] | None = None,
        tools: Sequence[Any] | None = None,
        tools_error: str = "",
    ) -> None:
        # (平台, 模型) -> 实例：一个模型一份图
        self.agents = agents
        # 平台 -> 该平台的默认模型（同平台多行时取优先级最高的那条）
        self.platform_default = platform_default
        # 全局默认（llm_providers 里 is_active 的那条）
        self.default_key = default_key
        # 构建失败的行，只用于排查；对话报错时也会带出第一条
        self.errors = errors or []
        # 整池共用的一份工具（建池时 load_tools 取一次）；每个 ModelAgent 的图都用它
        self.tools = list(tools) if tools is not None else []
        # 工具加载失败的那一句。单独存而不挤进 errors：那是代码问题，
        # 混进逐行错误会让 empty_error() 把「模型全部构建失败」归因到工具上
        self.tools_error = tools_error

    # ---------------- 构建与生命周期 ----------------

    @classmethod
    def _build_lock(cls) -> asyncio.Lock:
        """取当前事件循环可用的建池锁；换了 loop 就重建，绝不跨循环复用。"""
        loop = asyncio.get_running_loop()
        if cls._lock is None or cls._lock_loop is not loop:
            cls._lock = asyncio.Lock()
            cls._lock_loop = loop
        return cls._lock

    @classmethod
    def build(cls, rows: Iterable[Any]) -> "ChatManager":
        """由配置行构建整池；纯构建，不碰数据库。

        rows 吃 ORM 对象或有同名属性的对象，**顺序即优先级**：调用方按
        (is_active desc, id) 排好，于是同 (平台, 模型) 重复时保留第一条（它带着密钥），
        平台级默认取该平台最先出现的那条。测试可以直接传构造出来的行，不必连库。

        工具只取一次（整池共用一份实例）：它们本来就跟着配置走，重建时一起重取；
        取失败时退化成纯对话池（所有模型不带工具）而不是拖垮整池，原因见模块 docstring。
        """
        agents: dict[ModelPair, ModelAgent] = {}
        platform_default: dict[str, ModelPair] = {}
        default_key: ModelPair | None = None
        errors: list[str] = []
        tools_error = ""

        try:
            tools = load_tools()
        except Exception as exc:  # 工具坏了不该让模型全建不起来
            tools = []
            tools_error = f"{exc.__class__.__name__}: {exc}"
            logger.warning("工具注册表加载失败，本池退化为纯对话（不带工具）：%s", exc)

        for row in rows:
            model = (row.default_model or "").strip()
            if not model:
                continue  # 没填模型的行不构成可选项
            # 平台名也归一化一次：库里可能存着带空格的旧行，而前端拿到的是去空格的值，
            # 不归一会让选中的模型回传到 pick() 时对不上键
            platform = (row.platform or "").strip()
            pair: ModelPair = (platform, model)
            if pair in agents:
                continue  # 重复接入同一模型：保留优先级更高的一条

            try:
                agents[pair] = ModelAgent(
                    platform,
                    model,
                    supports_thinking=row.supports_thinking,
                    context_size=getattr(row, "context_size", 200000) or 200000,
                    api_key=row.api_key,
                    base_url=row.base_url,
                    tools=tools,
                )
            except Exception as exc:  # 单个模型失败不该拖垮整池
                errors.append(f"{platform}/{model}：{exc.__class__.__name__}: {exc}")
                logger.warning("模型 %s/%s 构建失败，已跳过：%s", platform, model, exc)
                continue

            platform_default.setdefault(platform, pair)
            if default_key is None and row.is_active:
                default_key = pair

        if default_key is None:
            # 整表没标记 active（或 active 那行构建失败）→ 退到第一个可用的模型
            default_key = next(iter(agents), None)

        return cls(
            agents,
            platform_default=platform_default,
            default_key=default_key,
            errors=errors,
            tools=tools,
            tools_error=tools_error,
        )

    @classmethod
    async def load(cls, db: AsyncSession) -> "ChatManager":
        """读全局配置建一个池（不改写 _instance）：生效行排最前，同状态按接入先后"""
        result = await db.scalars(
            select(LlmProvider).order_by(LlmProvider.is_active.desc(), LlmProvider.id)
        )
        return cls.build(list(result.all()))

    @classmethod
    async def get(cls, db: AsyncSession) -> "ChatManager":
        """取常驻池：lifespan 预热过就是纯判断，没预热（测试、启动时库不可达）才现建一次。

        冷路径加锁：load() 里的 `await db.scalars` 是个挂起点，不锁的话两个并发请求会各建
        一份完整的池（每张 ReAct 图白编译一次），后建的那份覆盖先建的。锁不改变正确性，
        只省掉这次重复构建；双重判断（拿锁后再看一次）是为了让排在后面的请求直接复用。
        """
        if cls._instance is not None:
            return cls._instance
        async with cls._build_lock():
            if cls._instance is None:
                cls._instance = await cls.load(db)
        return cls._instance

    @classmethod
    async def reload(cls, db: AsyncSession) -> "ChatManager":
        """管理员保存配置后重建整池并替换 _instance。

        是整体替换而不是原地 clear：正在流式回答的请求仍握着旧的 ModelAgent 引用，
        不会被换成半新半旧的池打断。顺带清掉 settings.llm 的 lru_cache，
        否则 .env 里改过的默认端点读不到 —— 必须先清再建：build_model() 是在建池时
        读 resolve_base_url() / get_llm_settings() 的（llm.py），清晚了新池仍用旧配置。
        load() 抛异常时赋值不会发生，旧池原样留着，不需要额外回滚。
        """
        get_llm_settings.cache_clear()
        cls._instance = await cls.load(db)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """丢弃常驻池（测试之间互不污染，或配置彻底清空后强制下次重建）"""
        cls._instance = None
        cls._lock = None
        cls._lock_loop = None

    # ---------------- 挑选实例 ----------------

    def empty_error(self) -> ChatConfigError:
        if self.errors:
            return ChatConfigError(f"管理员配置的模型全部构建失败，请联系管理员检查：{self.errors[0]}")
        return ChatConfigError("还没有可用的模型配置，请联系管理员在「设置 - 模型」里接入一个提供商")

    def pick(
        self,
        *,
        platform: str = "",
        model: str = "",
    ) -> ModelAgent:
        """按请求挑一个现成实例，三级回落：指定模型 > 平台默认 > 全局默认。

        入参先 strip：管理员在配置里多敲了空格、或客户端原样回传带空格的模型名，
        都不该造成「下拉里能看到、一发就报未接入」。

        思考开关不在这里定：一个模型只有一份图，快速/深度由 stream() 逐轮传入，
        所以 pick() 不再需要也不应该关心 thinking。
        """
        platform = (platform or "").strip()
        model = (model or "").strip()
        if not self.agents:
            raise self.empty_error()

        if model:
            pair = (platform, model) if platform else self._pair_of(model)
            if pair is None or pair not in self.agents:
                # 没给平台时别说「平台「未知」」：用户压根没选过平台，看了只会更困惑
                scope = f"平台「{platform}」" if platform else "任何已接入的平台"
                raise ChatConfigError(
                    f"{scope}未接入模型 {model}（或该行构建失败），"
                    "请联系管理员在「设置 - 模型」里补充"
                )
            return self.agents[pair]

        if platform:
            pair = self.platform_default.get(platform)
            if pair is None:
                raise ChatConfigError(
                    f"平台「{platform}」还没有管理员配置的模型，"
                    "请联系管理员在「设置 - 模型」里接入"
                )
        else:
            pair = self.default_key
        if pair is None:
            raise self.empty_error()
        return self.agents[pair]

    def _pair_of(self, model: str) -> ModelPair | None:
        """只给了模型名没给平台：按优先级找它所属的平台（同名多平台时取靠前那条）"""
        for pair in self.agents:
            if pair[1] == model:
                return pair
        return None

    # ---------------- 供 /settings/models 标注可用性 ----------------

    def has(self, platform: str, model: str) -> bool:
        """该 (平台, 模型) 是否真的建进了池。

        存在原因：模型下拉读的是 llm_providers 表，能不能聊取决于池。一行构建失败
        （密钥失效、平台不认参数）时它仍然出现在表里，不标注就会出现
        「下拉里选中了，一发就报未接入」。平台留空时按模型名查任一平台。
        """
        pair = (platform or "").strip()
        name = (model or "").strip()
        if not pair:
            found = self._pair_of(name)
            return found is not None
        return (pair, name) in self.agents

    def unavailable_reason(self, platform: str, model: str) -> str:
        """该行为什么不在池里：从 errors 里捡出对应那条，给前端做提示标题"""
        name = (model or "").strip()
        for item in self.errors:
            head, _, detail = item.partition("：")
            if head.partition("/")[2] == name or head == f"{platform}/{name}":
                return detail or item
        return "模型池尚未包含该行（可能配置保存后未重建）"

    def __repr__(self) -> str:
        return (
            f"<ChatManager models={len(self.agents)} tools={len(self.tools)} "
            f"default={self.default_key} errors={len(self.errors)}"
            f"{f' tools_error={self.tools_error!r}' if self.tools_error else ''}>"
        )
