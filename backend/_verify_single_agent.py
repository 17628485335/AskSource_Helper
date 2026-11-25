"""临时验证：真实配置行建池后，每个模型是否只有一份图、两种档位分别指向哪份模型"""

import asyncio

from app.chat import ChatManager
from auth.database import AsyncSessionLocal


def desc(model):
    if model is None:
        return None
    return {
        "name": getattr(model, "model_name", "?"),
        "extra_body": getattr(model, "extra_body", None),
    }


async def live(pool):
    """真发一轮：验证中间件 + context 接入真实 ChatOpenAI 后仍能流式产出"""
    from langchain_core.messages import HumanMessage

    agent = next(iter(pool.agents.values()))
    for flag in (False, True):
        events = []
        async for e in agent.stream([HumanMessage(content="用三个词回答：1+1")], thinking=flag):
            events.append(e)
        text = "".join(e["text"] for e in events if e["type"] == "delta")
        print(f"thinking={flag} events={len(events)} 首段={text[:40]!r}")


async def main():
    import sys

    async with AsyncSessionLocal() as db:
        pool = await ChatManager.load(db)
    print("pool:", pool)
    for pair, agent in pool.agents.items():
        print(
            f"- {pair} supports_thinking={agent.supports_thinking} "
            f"graph={'ok' if agent.agent is not None else 'MISSING'} "
            f"off={desc(agent.chat_model)} on={desc(agent.thinking_model)}"
        )
    ok = all(
        (a.thinking_model is None) == (not a.supports_thinking)
        and a.thinking_model is not a.chat_model
        for a in pool.agents.values()
    )
    print("支持行两份模型/不支持行只一份，且不是同一对象:", ok)
    print("effective_thinking(None/True/False):",
          [(a.supports_thinking, a.effective_thinking(None), a.effective_thinking(True),
            a.effective_thinking(False)) for a in pool.agents.values()])
    if "--live" in sys.argv:
        await live(pool)


asyncio.run(main())
