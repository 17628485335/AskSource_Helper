"""按预设类型调用 LLM 生成上下文段内容。

Soul / Identity / Agents Guide / User Profile 是四类固定用途的 agent 文档，
生成时各用一份专门的 system prompt；generated / memory 没有内容正文，不提供生成。
本模块只负责 prompt 与结果清洗，不取模型、不碰数据库。
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

SYSTEM_PROMPTS: dict[str, str] = {
    "soul": """你是一个 Agent 配置助手。请为一个 AI Agent 生成「Soul」段内容，它定义 Agent 的性格、语气与行为底线。
要求：
- 用中文写 5～8 条，每条一行，以「- 」开头。
- 必须覆盖三个维度：性格特质、说话语气、不可逾越的行为底线。
- 写成可直接粘贴进配置文件的短句，不要解释，不要标题，不要 markdown 代码块。""",
    "identity": """你是一个 Agent 配置助手。请为一个 AI Agent 生成「Identity」段内容，它定义 Agent 的身份与自我介绍口径。
要求：
- 用中文写 4～7 条，每条一行，以「- 」开头。
- 必须覆盖：身份名称、角色定位、核心能力、服务边界、用户问「你是谁」时怎么回答。
- 不要编造具体公司名或产品版本号，保持可复用；只输出内容本身。""",
    "agents_guide": """你是一个 Agent 配置助手。请为一个 AI Agent 生成「Agents Guide」段内容，它是 Agent 的工作方式指南。
要求：
- 用中文写 5～8 条，每条一行，以「- 」开头。
- 必须覆盖：什么时候调用工具、引用怎么标注、回答怎么分段、信息不足时怎么处理、什么时候需要向用户确认。
- 只写通用工作规范，不要写某个具体业务的答案；只输出内容本身。""",
    "user_profile": """你是一个 Agent 配置助手。请生成「User Profile」段内容，它描述目标用户的稳定事实与偏好，作为事实参考注入，不是给 Agent 的规则。
要求：
- 用中文写 4～7 条，每条一行，以「- 」开头。
- 覆盖：称呼与语言偏好、专业背景、常用术语、回答详略偏好、需要避免的表达。
- 用可复用的占位描述（如「用户偏好中文」），不要编造具体姓名、公司或隐私信息；只输出内容本身。""",
}

MAX_GENERATED_CHARS = 8000


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def build_messages(
    kind: str,
    *,
    current: str = "",
    hint: str = "",
    variant: int = 0,
) -> list[Any]:
    """构造一次生成的消息；current 作为润色参考，variant>0 表示「换一换」。"""
    lines = ["请按系统要求生成内容。"]
    if current.strip():
        lines.extend(["", "当前内容（请在此基础上润色，不要照抄）：", current.strip()])
    if hint.strip():
        lines.extend(["", f"额外要求：{hint.strip()}"])
    if variant > 0:
        lines.extend(
            ["", f"这是第 {variant + 1} 次生成，请换一个切入角度和措辞，避免与上一次雷同。"]
        )
    return [
        SystemMessage(content=SYSTEM_PROMPTS[kind]),
        HumanMessage(content="\n".join(lines)),
    ]


def clean_generated(content: Any) -> str:
    """去掉模型常见的 markdown 代码块围栏，并限制长度。"""
    text = _text_of(content).strip()
    if text.startswith("```"):
        text = text[3:]
        if "\n" in text:
            text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()[:MAX_GENERATED_CHARS]


async def generate_context_content(
    model: Any,
    kind: str,
    *,
    current: str = "",
    hint: str = "",
    variant: int = 0,
) -> str:
    if kind not in SYSTEM_PROMPTS:
        raise ValueError(f"不支持的上下文类型: {kind}")
    response = await model.ainvoke(
        build_messages(kind, current=current, hint=hint, variant=variant)
    )
    return clean_generated(getattr(response, "content", ""))
