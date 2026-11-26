"""Tool 注册表：用 @register_tool 把 BaseTool 子类登记为可供 graph 使用的工具

设计要点：
- 每个工具是一个继承 langchain BaseTool 的类；装饰器只登记「类」而非实例，
  避免导入期就构造 pydantic 对象，也便于工具带构造参数时自行实例化。
- 元数据以「类字段」为优先来源：BaseTool 把 name / description 声明为必填字段（无默认值），
  类层面只能从 ``cls.model_fields[...].default`` 读到值（pydantic v2 已把字段移出类命名空间）。
  装饰器也接受 name / description，但不是「只存进注册表」（那样实例不会跟着变，模型
  看到的还是旧名）：而是写回类的字段默认值 + model_rebuild(force=True)，所以注册表的键、
  实例的 tool.name、convert_to_openai_tool(实例) 三者始终一致。
  其余装饰器参数（category / icon / dangerous / requires_env / …）纯属注册侧信息，
  不进实例也不发给模型，供接口展示、分组与人工排查用。
- 注册表是模块级 dict，只提供 注册 / 查询 / 取实例 三类操作，
  新增工具只需加一个被装饰的类，不改任何注册逻辑（开闭原则）。
- 「自动挂载」由 enabled_by_default 与 dangerous 共同决定（见 ToolSpec.auto_mount）：
  get_tools() 不点名时只回未标危险的项，于是有副作用的工具必须被显式请求才会进图。
- requires_env / needs_root 只做声明式诊断（unmet_requirements）：本项目没有任何
  load_dotenv，backend/.env 的键不会进 os.environ，所以不能拿它们当挂载开关。
"""

import os
from enum import Enum
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ToolCategory",
    "DEFAULT_ICON",
    "ToolSpec",
    "register_tool",
    "list_tool_specs",
    "get_tool_spec",
    "get_tool",
    "get_tools",
    "tool_is_available",
    "unmet_requirements",
    "unregister_tool",
    "clear_tools",
]

T = TypeVar("T")

# 工具名 -> 注册信息；实例缓存在 _TOOL_INSTANCES，按需构造
_TOOL_REGISTRY: dict[str, "ToolSpec"] = {}
_TOOL_INSTANCES: dict[str, Any] = {}


class ToolCategory(str, Enum):
    """工具粗分类：列表分组与按类批量取用都用它（值就是存进注册表的字符串）"""

    CORE = "core"      # 不依赖外部服务的基础能力
    SEARCH = "search"  # 联网检索与网页读取
    DATA = "data"      # 读写数据 / 文件
    SYSTEM = "system"  # 会动本机或第三方账号状态


# 未声明图标时的默认值（取 lucide 图标名，与前端其余图标一致）
DEFAULT_ICON = "wrench"


class ToolSpec(BaseModel):
    """一个已注册工具的声明信息"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    description: str = ""
    tool_class: type
    tags: tuple[str, ...] = Field(default=())
    # 分类与展示
    category: str = ToolCategory.CORE.value
    icon: str = DEFAULT_ICON
    # 中文展示名：前端侧边栏等处显示，不进模型提示词
    label: str = ""
    # 同一轮对话内允许调用的次数；0（默认）表示不限制
    max_calls: int = 0
    example: str = ""
    # 风险与前置条件：都只是声明，运行时的真实探测仍走 available()
    dangerous: bool = False
    requires_env: tuple[str, ...] = ()
    needs_root: bool = False
    # 是否在 get_tools() 不点名时被自动挂进模型图
    enabled_by_default: bool = True

    @property
    def auto_mount(self) -> bool:
        """该不该被自动挂载：标了 dangerous 的工具即使没关开关也要显式点名"""
        return self.enabled_by_default and not self.dangerous


def _field_default(cls: type, key: str) -> str | None:
    """读取 BaseTool 子类上 name / description 字段的默认值（未声明则返回 None）"""
    field = getattr(cls, "model_fields", {}).get(key)
    if field is None:
        return None
    default = field.default
    return default if isinstance(default, str) and default else None


def _match_tags(spec: "ToolSpec", tags: Iterable[str] | None) -> bool:
    """tags 为空表示不过滤；否则要求工具的标签覆盖全部所需标签"""
    wanted = tuple(tags or ())
    return not wanted or set(wanted).issubset(spec.tags)


def _norm_category(value: str | ToolCategory) -> str:
    """分类归一（枚举项与字符串都行，大小写不敏感）

    不能直接 str(value)：Python 3.11+ 里 `(str, Enum)` 混入类的 __str__ 已被 Enum 接管，
    str(ToolCategory.SEARCH) 得到的是 "ToolCategory.SEARCH"。写错的分类在导入期就报错，
    而不是静默分成另一类。
    """
    if isinstance(value, ToolCategory):
        return value.value
    try:
        return ToolCategory(str(value).strip().lower()).value
    except ValueError as exc:
        valid = "、".join(item.value for item in ToolCategory)
        raise ValueError(f"未知的工具分类 {value!r}，可用: {valid}") from exc


def _apply_default(tool_cls: type, key: str, value: str) -> None:
    """把装饰器传来的 name / description 写回类的字段默认值。

    光存进注册表没用：模型看到的 tool.name / description 取自实例，而 BaseTool 是
    pydantic 模型，建类时已经把字段编进 core schema。所以改 model_fields 的默认值
    再 force rebuild（实测实例与 ToolNode.tools_by_name 都跟着变）。
    """
    field = getattr(tool_cls, "model_fields", {}).get(key)
    if field is None:
        raise TypeError(f"{tool_cls.__name__} 没有 {key} 字段，无法用 register_tool({key}=...) 覆盖")
    field.default = value
    tool_cls.model_rebuild(force=True)


def register_tool(
    cls: type[T] | None = None,
    *,
    category: str = ToolCategory.CORE,
    icon: str = DEFAULT_ICON,
    label: str = "",
    max_calls: int = 0,
    tags: list[str] | None = None,
    dangerous: bool = False,
    requires_env: list[str] | None = None,
    needs_root: bool = False,
    enabled_by_default: bool = True,
    example: str = "",
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """把一个 BaseTool 子类登记进工具表，原样返回该类。

    默认写法是把 name / description 声明成带默认值的类字段::

        @register_tool
        class EchoTool(BaseTool):
            name: str = "echo"
            description: str = "回显输入"

            def _run(self, query: str) -> str:
                return query

    装饰器的其余参数是注册侧元数据（不进实例、不发给模型）；category / tags 用于
    分组取用，label（中文展示名）/ icon / example 给前端展示，dangerous /
    requires_env / needs_root / enabled_by_default 描述风险与前置条件::

        @register_tool(
            tags=["search"],
            category=ToolCategory.SEARCH,
            icon="globe",
            label="联网搜索",
            max_calls=3,
            requires_env=["TAVILY_API_KEY"],
            example='web_search(query="2026 年诺贝尔物理学奖")',
        )
        class WebSearchTool(BaseTool):
            name: str = "web_search"
            description: str = "联网检索"

    name / description 也可以在装饰器里给：它们会被写回类的字段默认值（见
    _apply_default），所以实例与模型看到的也是新值；两边都给时以装饰器为准。
    两种写法（裸用 / 带 kwargs）都支持；name 重复会直接报错，避免静默覆盖。
    max_calls 是同一轮对话内的调用上限，0 表示不限制；负值直接报错。
    """
    if max_calls < 0:
        raise ValueError("register_tool(max_calls=...) 不能为负数；0 表示不限制")

    def decorate(tool_cls: type[T]) -> type[T]:
        from langchain_core.tools import BaseTool

        if not isinstance(tool_cls, type) or not issubclass(tool_cls, BaseTool):
            raise TypeError(f"@register_tool 只能装饰 BaseTool 子类，收到: {tool_cls!r}")

        for key, value in (("name", name), ("description", description)):
            if value is None:
                continue
            if not value.strip():
                raise ValueError(f"register_tool({key}=...) 不能是空字符串")
            _apply_default(tool_cls, key, value.strip())

        resolved = _field_default(tool_cls, "name")
        if not resolved:
            raise ValueError(
                f"{tool_cls.__name__} 必须声明 name 字段默认值，例如：name: str = \"{tool_cls.__name__.lower()}\""
            )
        desc = _field_default(tool_cls, "description")
        if not desc:
            raise ValueError(f"{tool_cls.__name__} 必须声明 description 字段默认值（会作为工具说明传给模型）")
        if resolved in _TOOL_REGISTRY:
            raise ValueError(f"工具名重复: {resolved}（已注册 {_TOOL_REGISTRY[resolved].tool_class.__name__}）")

        _TOOL_REGISTRY[resolved] = ToolSpec(
            name=resolved,
            description=desc,
            tool_class=tool_cls,
            tags=tuple(str(t).strip() for t in (tags or ()) if str(t).strip()),
            category=_norm_category(category),
            icon=str(icon).strip() or DEFAULT_ICON,
            label=str(label).strip() or resolved,
            max_calls=max_calls,
            example=str(example).strip(),
            dangerous=dangerous,
            requires_env=tuple(str(e).strip() for e in (requires_env or ()) if str(e).strip()),
            needs_root=needs_root,
            enabled_by_default=enabled_by_default,
        )
        return tool_cls

    # 裸用 @register_tool 时第一个位置参数就是被装饰的类
    if cls is not None:
        return decorate(cls)
    return decorate


def list_tool_specs(
    tags: Iterable[str] | None = None,
    *,
    category: str | None = None,
) -> list[ToolSpec]:
    """按名称排序返回注册信息，可按标签 / 分类过滤（供接口 / 调试展示）"""
    wanted = _norm_category(category) if category is not None else None
    return sorted(
        (
            s
            for s in _TOOL_REGISTRY.values()
            if _match_tags(s, tags) and (wanted is None or s.category == wanted)
        ),
        key=lambda s: s.name,
    )


def get_tool_spec(name: str) -> "ToolSpec | None":
    """取单个工具的注册信息；未注册返回 None"""
    return _TOOL_REGISTRY.get(name)


def get_tool(name: str, **kwargs: Any) -> Any:
    """按名称取 BaseTool 实例；无构造参数时走缓存复用单例。

    传了 kwargs 说明该工具需要运行时依赖（如 db、api_key），
    此时每次新建实例且不写缓存。
    """
    spec = _TOOL_REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"未注册的工具: {name}，可用: {sorted(_TOOL_REGISTRY)}")

    if not kwargs and name in _TOOL_INSTANCES:
        return _TOOL_INSTANCES[name]

    instance = spec.tool_class(**kwargs)
    if not kwargs:
        _TOOL_INSTANCES[name] = instance
    return instance


def get_tools(
    names: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    *,
    category: str | None = None,
    include_disabled: bool = False,
    **kwargs: Any,
) -> list[Any]:
    """批量取 BaseTool 实例，可直接传给 create_agent(model=..., tools=...)。

    names 与 tags / category 都不给时返回全部可自动挂载的工具。

    不点名（只按 tags / category 筛）时尊重开关：跳过 enabled_by_default=False
    与 dangerous 的项，建池这种「默认拿一批」的调用不会误挂危险工具；
    而 names 是显式点名，开关一概不管（include_disabled 只影响隐式分支）。
    """
    if names is not None:
        return [get_tool(n, **kwargs) for n in names]
    specs = list_tool_specs(tags, category=category)
    if not include_disabled:
        specs = [s for s in specs if s.auto_mount]
    return [get_tool(s.name, **kwargs) for s in specs]


def tool_is_available(tool: Any) -> bool:
    """问一个工具实例「前置条件满足了吗」；工具体自己决定怎么回答。

    工具类可以选实现一个无参类方法 ``available() -> bool``（典型场景：没配外部密钥
    就不该挂进图）。没实现就算可用 —— 绝大多数工具是无条件的。

    探测本身报错也当作不可用：一个查前置条件都能抛异常的工具，挂上去只会多一次失败，
    而这里宁可少一个工具，也不能让建池整体失败。
    """
    probe = getattr(type(tool), "available", None)
    if not callable(probe):
        return True
    try:
        return bool(probe())
    except Exception:
        return False


def unmet_requirements(name: str) -> list[str]:
    """把声明式前置条件（requires_env / needs_root）翻译成「还缺什么」，供提示与排查。

    只用于人工诊断，不是挂载开关：本项目没有 load_dotenv，backend/.env 里的键不会进
    os.environ，所以只写在 .env 里的密钥也会被这里报成缺失。真正决定要不要挂进图的是
    tool_is_available() —— 由工具自己读它自己的 Settings 对象（见 app/settings/）。
    """
    spec = _TOOL_REGISTRY.get(name)
    if spec is None:
        return [f"未注册的工具: {name}"]
    gaps: list[str] = []
    for key in spec.requires_env:
        if not (os.environ.get(key) or "").strip():
            gaps.append(f"缺少环境变量 {key}（进程环境未设；只写在 .env 里时这里也会报）")
    if spec.needs_root and os.geteuid() != 0:
        gaps.append("该工具需要 root 权限，当前进程不是")
    return gaps


def unregister_tool(name: str) -> bool:
    """移除一个注册项（主要给测试和热重载用）；返回是否真的删掉了"""
    _TOOL_INSTANCES.pop(name, None)
    return _TOOL_REGISTRY.pop(name, None) is not None


def clear_tools() -> None:
    """清空注册表与实例缓存"""
    _TOOL_REGISTRY.clear()
    _TOOL_INSTANCES.clear()
