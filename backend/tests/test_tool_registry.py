"""工具注册表的声明式元数据（category / icon / dangerous / …）

守住三件事：
- 装饰器参数确实进了 ToolSpec，且能按分类 / 标签筛；
- name / description 覆盖是「写回类字段」而不是只存注册表 —— 否则模型看到的还是旧名；
- 隐式取用（get_tools() 不点名）会跳过 enabled_by_default=False 与 dangerous 的项。

临时注册的工具一律在 finally 里 unregister_tool，否则会漏进其它用例的 get_tools()。
"""

import os
from typing import Any, ClassVar

import pytest
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from app.graph.tools import (
    ToolCategory,
    clear_tools,
    get_tool,
    get_tool_spec,
    get_tools,
    list_tool_specs,
    register_tool,
    unregister_tool,
    unmet_requirements,
)

# 导入包 = 把内置工具注进表；本文件不依赖其它用例的导入顺序
import app.tools  # noqa: E402, F401


def _make(tool_name: str, **meta: Any) -> type[BaseTool]:
    """造一个被装饰过的最小工具类

    入参叫 tool_name 而不是 name：类体里写 ``name: str = name`` 会因为同名
    遮蔽而报 NameError（带注解的类体赋值取不到外层同名变量）。
    """

    @register_tool(**meta)
    class _Tool(BaseTool):
        name: str = tool_name
        description: str = f"{tool_name} 的说明"

        def _run(self, query: str = "") -> str:  # type: ignore[override]
            return query

    return _Tool


def _cleanup(*names: str):
    for name in names:
        unregister_tool(name)


@pytest.fixture(autouse=True)
def restore_registry():
    """注册表是模块级全局：用例跑完把两张表原样放回，临时工具不会漏进其它用例"""
    import app.graph.tools as registry_module

    specs = dict(registry_module._TOOL_REGISTRY)
    instances = dict(registry_module._TOOL_INSTANCES)
    yield
    registry_module._TOOL_REGISTRY.clear()
    registry_module._TOOL_REGISTRY.update(specs)
    registry_module._TOOL_INSTANCES.clear()
    registry_module._TOOL_INSTANCES.update(instances)


# ---------------------------------------------------------------- 声明信息


def test_metadata_lands_on_spec():
    _make(
        "meta_probe",
        category=ToolCategory.DATA,
        icon="database",
        tags=["probe", " search "],  # 顺手验证首尾空格的归一
        dangerous=True,
        requires_env=["SOME_TOKEN", " "],
        needs_root=True,
        enabled_by_default=False,
        example="meta_probe(query='x')",
    )
    try:
        spec = get_tool_spec("meta_probe")
        assert spec is not None
        assert spec.category == "data", "分类要存成纯字符串，别存成 Enum repr"
        assert spec.icon == "database"
        assert spec.tags == ("probe", "search")
        assert spec.dangerous is True
        assert spec.requires_env == ("SOME_TOKEN",), "空白项该被丢掉"
        assert spec.needs_root is True
        assert spec.enabled_by_default is False
        assert spec.example == "meta_probe(query='x')"
        assert spec.auto_mount is False
    finally:
        _cleanup("meta_probe")


def test_defaults_are_a_plain_auto_mounting_tool():
    _make("plain_probe")
    try:
        spec = get_tool_spec("plain_probe")
        assert spec.category == ToolCategory.CORE.value
        assert spec.icon == "wrench"
        assert spec.tags == ()
        assert spec.dangerous is False and spec.needs_root is False
        assert spec.requires_env == () and spec.example == ""
        assert spec.auto_mount is True
    finally:
        _cleanup("plain_probe")


def test_unknown_category_fails_at_import_time():
    """分类写错宁可炸在导入期，也别静默落成另一类"""
    with pytest.raises(ValueError, match="未知的工具分类"):

        @register_tool(category="seach")
        class _Typo(BaseTool):
            name: str = "typo_probe"
            description: str = "d"

            def _run(self, query: str = "") -> str:  # type: ignore[override]
                return query

    assert get_tool_spec("typo_probe") is None


# ---------------------------------------------------------------- 筛与取


def test_filter_by_category_and_tags():
    _make("cat_probe_a", category=ToolCategory.SEARCH, tags=["probe"])
    _make("cat_probe_b", category=ToolCategory.DATA, tags=["probe"])
    try:
        # search 分类里本就有 web_search / read_url，只能断言包含关系
        search = [s.name for s in list_tool_specs(category="search")]
        assert "cat_probe_a" in search and "cat_probe_b" not in search
        assert [s.name for s in list_tool_specs(category=ToolCategory.DATA)] == ["cat_probe_b"]
        assert {s.name for s in list_tool_specs(["probe"])} == {"cat_probe_a", "cat_probe_b"}
        # 分类与标签是且关系
        assert list_tool_specs(["probe"], category="core") == []
        with pytest.raises(ValueError, match="未知的工具分类"):
            list_tool_specs(category="nope")
    finally:
        _cleanup("cat_probe_a", "cat_probe_b")


def test_dangerous_and_disabled_are_not_auto_mounted():
    """建池走的是 get_tools() 不点名，危险工具必须显式请求才进图"""
    _make("off_probe", enabled_by_default=False)
    _make("risk_probe", dangerous=True)
    try:
        names = [t.name for t in get_tools()]
        assert "off_probe" not in names and "risk_probe" not in names
        # 点名就要给（这是「管理员显式启用」的通路）
        assert [t.name for t in get_tools(names=["off_probe", "risk_probe"])] == [
            "off_probe",
            "risk_probe",
        ]
        assert {"off_probe", "risk_probe"} <= {t.name for t in get_tools(include_disabled=True)}
        # 按标签取时也仍然过滤掉
        _make("off_tagged", tags=["probe2"], enabled_by_default=False)
        try:
            assert get_tools(tags=["probe2"]) == []
            assert len(get_tools(tags=["probe2"], include_disabled=True)) == 1
        finally:
            _cleanup("off_tagged")
    finally:
        _cleanup("off_probe", "risk_probe")


# ---------------------------------------------------------------- name / description 覆盖


def test_name_override_reaches_the_instance():
    """只把 name 存进注册表是没用的：模型看到的工具名取自实例"""
    _make("orig_name", name="renamed_probe", description="  覆盖后的说明  ")
    try:
        assert get_tool_spec("renamed_probe") is not None, "注册键应跟覆盖后的名字一致"
        tool = get_tool("renamed_probe")
        assert tool.name == "renamed_probe"
        assert tool.description == "覆盖后的说明"
        spec = convert_to_openai_tool(tool)
        assert spec["function"]["name"] == "renamed_probe"
        assert spec["function"]["description"] == "覆盖后的说明"
        # 原类字段值不该留下第二个注册项
        assert get_tool_spec("orig_name") is None
    finally:
        _cleanup("renamed_probe")


def test_blank_override_is_rejected():
    for kwargs in ({"name": "  "}, {"description": ""}):
        with pytest.raises(ValueError, match="不能是空字符串"):
            _make("blank_probe", **kwargs)
        _cleanup("blank_probe")


def test_missing_name_field_still_fails_loudly():
    """既不写类字段也不传装饰器 → 老报错不能丢"""

    class _NoName(BaseTool):
        description: str = "d"

        def _run(self, query: str = "") -> str:  # type: ignore[override]
            return query

    with pytest.raises(ValueError, match="必须声明 name 字段默认值"):
        register_tool(_NoName)


def test_duplicate_name_reported():
    _make("dup_probe")
    try:
        with pytest.raises(ValueError, match="工具名重复: dup_probe"):
            _make("dup_probe")
    finally:
        _cleanup("dup_probe")


def test_classvar_args_schema_survives_the_rebuild():
    """覆盖 description 会 force rebuild，不能顺手把 ClassVar 的 args_schema 抖掉"""

    class _Args(BaseModel):
        query: str = Field(default="", description="要查的东西")

    class _Typed(BaseTool):
        name: str = "typed_probe"
        description: str = "d"
        args_schema: ClassVar[Any] = _Args

        def _run(self, query: str = "") -> str:  # type: ignore[override]
            return query

    register_tool(_Typed, description="重建后的说明")
    try:
        tool = get_tool("typed_probe")
        assert tool.description == "重建后的说明"
        assert set(tool.args) == {"query"}
        params = convert_to_openai_tool(tool)["function"]["parameters"]["properties"]
        assert list(params) == ["query"]
    finally:
        _cleanup("typed_probe")


def test_override_does_not_leak_into_base_tool():
    """写回默认值只能影响被装饰的那个类

    若 pydantic 让子类共用父类的 FieldInfo，一次覆盖就会把后面所有工具的默认名都改掉。
    """
    _make("leak_probe", name="leaked_name")
    try:
        assert BaseTool.model_fields["name"].default != "leaked_name"
        _make("later_probe")
        assert get_tool("later_probe").name == "later_probe"
        _cleanup("later_probe")
    finally:
        _cleanup("leaked_name")


# ---------------------------------------------------------------- 前置条件诊断


def test_unmet_requirements_reads_process_env(monkeypatch):
    monkeypatch.delenv("PROBE_TOKEN", raising=False)
    monkeypatch.setenv("PROBE_OK", "yes")
    _make("env_probe", requires_env=["PROBE_TOKEN", "PROBE_OK"])
    try:
        gaps = unmet_requirements("env_probe")
        assert len(gaps) == 1 and "PROBE_TOKEN" in gaps[0]
        assert "PROBE_OK" not in gaps[0]
        # 已满足时是空列表，而不是 None
        monkeypatch.setenv("PROBE_TOKEN", "tvly-x")
        assert unmet_requirements("env_probe") == []
    finally:
        _cleanup("env_probe")


def test_unmet_requirements_covers_unknown_tool_and_root():
    assert "未注册的工具" in unmet_requirements("definitely_not_registered")[0]
    if not hasattr(os, "geteuid"):  # pragma: no cover - Windows
        pytest.skip("geteuid 仅类 unix 平台有")
    _make("root_probe", needs_root=True)
    try:
        gaps = unmet_requirements("root_probe")
        if os.geteuid() == 0:  # pragma: no cover - 以 root 跑测试时应当闭嘴
            assert gaps == []
        else:
            assert len(gaps) == 1 and "root" in gaps[0]
    finally:
        _cleanup("root_probe")


# ---------------------------------------------------------------- 真实工具的声明


def test_search_tools_declare_their_key_and_category():
    """web_search / read_url 的元数据必须与实现一致，否则前端会误导用户"""
    for name in ("web_search", "read_url"):
        spec = get_tool_spec(name)
        assert spec is not None, f"{name} 未注册（app/tools/__init__.py 漏了 import？）"
        assert spec.category == "search"
        assert spec.requires_env == ("TAVILY_API_KEY",)
        assert spec.enabled_by_default is True and spec.dangerous is False
        assert spec.example and spec.icon


def test_clear_tools_drops_instances_too():
    """clear_tools() 连实例缓存一起清：只清表会让热重载后仍拿到旧对象"""
    _make("clear_probe")
    get_tool("clear_probe")
    clear_tools()
    assert list_tool_specs() == []
    assert get_tool_spec("clear_probe") is None
    with pytest.raises(KeyError, match="未注册的工具"):
        get_tool("clear_probe")
    # 内置工具由 autouse fixture 放回，下一个用例不会看到空表
