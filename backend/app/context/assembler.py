"""上下文工程基础模块：能力快照。

旧的 build_context 装配链路已由“生成系统提示词时写入 agent_prompts”替代；
保留本模块只用于 Skills Snapshot 生成。
"""

from app.graph import list_tool_specs
import app.tools  # noqa: F401  确保工具注册到 registry，Skills Snapshot 才拿得到内容


def build_skills_snapshot(tool_names: list[str] | None) -> str:
    """从工具注册表生成能力快照；不落库正文，避免与真实工具状态漂移。"""
    if tool_names is not None and not tool_names:
        return "本 Agent 未启用任何工具。"

    specs = list_tool_specs()
    if tool_names is not None:
        wanted = set(tool_names)
        specs = [spec for spec in specs if spec.name in wanted]
    else:
        specs = [spec for spec in specs if spec.auto_mount]

    if not specs:
        return "当前没有可用工具。"

    lines = ["可用工具："]
    for spec in specs:
        label = spec.label or spec.name
        suffix = f"，单轮最多 {spec.max_calls} 次" if spec.max_calls > 0 else ""
        lines.append(f"- {spec.name}（{label}）：{spec.description}{suffix}")
    return "\n".join(lines)


