# 上下文压缩记忆执行计划

> 日期：2026-11-26  
> 状态：待执行  
> 范围：先实现「压缩记忆」，长期记忆单独分期，不与压缩摘要混用。

## 1. 核心定义

### 1.1 压缩记忆

压缩记忆是对**当前 session 的 messages 进行压缩**：

- 输入：`chat_messages` + `chat_tool_calls`
- 输出：当前会话范围内的一段压缩摘要
- 目的：控制单次请求送入模型的上下文长度
- 生命周期：属于当前 session
- 触发条件：历史 token 超阈值、消息数过多、手动触发

压缩记忆解决的是：

> 这个会话太长，模型上下文装不下了。

### 1.2 长期记忆

长期记忆是跨 session 的结构化事实：

- 输入：多轮对话、用户偏好、稳定事实
- 输出：一条条可检索的结构化 memory
- 目的：下次会话仍然记得用户和项目背景
- 生命周期：user × agent
- 触发条件：一轮结束后抽取、定期整理、用户手工维护

长期记忆解决的是：

> 下次会话也记得用户稳定的偏好和事实。

两者不是同一个东西。压缩摘要不自动写入长期记忆；长期记忆也不替代压缩摘要。

---

## 2. 当前代码基线

当前历史加载只取最近 20 条消息：

```python
DEFAULT_HISTORY_LIMIT = 20
```

`to_lc_messages()` 会把 ORM 消息转成 LangChain 消息，但 `tools` 角色会被跳过。

需要特别说明：数据库里**已经保存了**工具调用标识：`chat_tool_calls.call_id`，同时也保存了 `message_id / turn_id / result_text / citations_json`。当前问题不是没存 `call_id`，而是：

1. `to_lc_messages(rows)` 只接收 `ChatMessage` 列表；
2. 它没有按 `message_id / turn_id` 把 `ChatToolCall` 查出来并还原成 LangChain `ToolMessage`；
3. `ChatMessage` 自身也没有 `tool_call_id` 字段；
4. 同时，助手消息里的 `AIMessage.tool_calls` 也没有从 `chat_tool_calls` 还原。

所以当前转换结果是：

```text
chat_messages -> HumanMessage / AIMessage / SystemMessage
tools         -> skip
```

后续压缩时，工具结果应直接从 `chat_tool_calls.result_text` 读取，不需要先修通 `ToolMessage` 还原链路；如果以后要恢复完整 tool message 上下文，则需要同时还原：

```text
AIMessage.tool_calls + ToolMessage(tool_call_id=...)
```

二者缺一不可。

`chat_messages.tokens` 字段存在，但当前对话链路没有真正写入，值一直为 0。

`agents` 和 `agent_prompts` 表已经创建并迁移完成，当前默认有一条启用的 `chat` agent 和 v1 提示词。

---

## 3. 总体原则

1. **不删原始消息**：压缩只建立边界，不物理删除 `chat_messages`。
2. **按 turn 压缩**：以 `turn_id` 为最小压缩单位，不把 user、tool result、assistant answer 拆开。
3. **前端历史不变**：前端仍能查看完整历史；只有模型上下文使用压缩结果。
4. **工具结果优先压**：`chat_tool_calls.result_text` 通常是最大 token 来源。
5. **先估算再调用**：请求前用 tokenizer 估算，请求后用模型返回的 usage 校准。
6. **压缩和长期记忆隔离**：压缩摘要是 session 级上下文；长期记忆是跨 session 知识。

---

## 4. Phase 0：上下文 token 计量基础

### 目标

先能估算请求前 token，并记录请求后真实 token。

### 任务

1. `backend/requirements.txt` 增加 `tiktoken`。
2. 新建 `backend/app/context/tokenizer.py`：

   - `count_text_tokens(text, model)`
   - `count_messages_tokens(messages, model)`
   - `count_tools_tokens(tools, model)`

3. 建立编码映射：

   - `gpt-4o*` → `o200k_base`
   - 其他 OpenAI 兼容模型 → `cl100k_base`
   - 未知模型统一回退 `cl100k_base`

4. 在 `ModelAgent.astream()` 的 `on_chat_model_end` 里读取：

   - `input_tokens`
   - `output_tokens`
   - `total_tokens`

5. 新增协议事件 `usage`，先只给后端 service 消费，前端可忽略。
6. `chat_messages` 增加：

   - `input_tokens`
   - `output_tokens`

   `tokens` 字段继续保留，写 total，兼容旧代码。

### 验收

- 请求前能估算 system prompt、tools、history、当前输入的总 token。
- 请求后能把真实 usage 写入 assistant 消息。
- 前端不因新增 `usage` 事件出错。

---

## 5. Phase 1：压缩记忆表结构与加载策略

### 新增表 `chat_compactions`

```text
id
session_id
from_turn_id
to_turn_id
summary
tokens_before
tokens_after
source_hash
model
prompt_version
created_at
```

说明：

- `from_turn_id / to_turn_id`：本次压缩覆盖的 turn 范围。
- `summary`：压缩摘要正文。
- `source_hash`：源消息内容 hash，避免同一批消息重复压缩。
- `tokens_before / tokens_after`：用于验证压缩是否有效。

### `chat_sessions` 增加字段

```text
compacted_upto_turn_id
```

含义：

> 这个 `turn_id` 及之前的轮次已经被压缩，后续模型上下文不再加载原文。

### 新增服务函数

在 `backend/app/session/service.py` 增加：

- `create_compaction(...)`
- `get_latest_compaction(session_id)`
- `load_model_history(db, session_id, ...)`

`load_model_history()` 返回：

```text
[压缩摘要] + [compacted_upto_turn_id 之后的消息]
```

前端历史列表继续使用 `load_messages()`，不受影响。

### 验收

- 压缩后前端历史消息不减少。
- 模型实际上下文只包含摘要和最近未压缩消息。
- 压缩记录可查询、可审计。

---

## 6. Phase 2：压缩执行器

### 新建模块

```text
backend/app/context/compactor.py
```

核心函数：

```python
async def maybe_compact(
    db,
    *,
    session_id,
    user_id,
    messages,
    tool_calls_by_turn,
    agent_ctx,
    model,
) -> list[Any]:
    ...
```

### 触发条件

满足任一条件即触发压缩：

1. 估算 token 超过模型上下文窗口的 70%～80%。
2. 未压缩消息数超过配置阈值，例如 40 条。
3. 手动调用压缩接口。

### 压缩单位

以 `turn_id` 为单位，不拆分一轮。

每轮输入包括：

- user 正文
- assistant 正文
- `chat_tool_calls.result_text`
- 工具名、耗时、引用信息

### 保留策略

- 最近 N 轮原文不压缩，默认 4～6 轮。
- 只压缩更早的 turn。
- 工具结果优先压缩，因为通常最占 token。

### 压缩输出格式

提示词要求模型输出固定结构：

```text
1. 会话目标
2. 已确认事实
3. 用户偏好
4. 关键决定
5. 工具检索结论
6. 未解决问题
7. 被压缩的 turn_id 范围
```

摘要写入 `chat_compactions.summary`。

### 压缩模型

新增内部 agent：

```text
agent_key = memory_compressor
```

特点：

- 不挂载任何工具
- 提示词存在 `agent_prompts`
- 使用快速模型，降低压缩成本

### 验收

- 旧工具结果不再原样进入下一轮模型上下文。
- 压缩前后 token 数都落库。
- 摘要保留引用编号和工具结论，不凭空生成事实。
- 重复压缩不会覆盖原始消息。

---

## 7. Phase 3：接入 chat 请求链路

当前 `backend/app/chat/service.py` 中通过 `app.context.history.load_history()` 取历史，后续改为压缩感知的历史加载。

### 改造

把：

```python
history = await load_history(db, sid)
```

改成：

```python
history = await context_service.build_model_context(
    db,
    session_id=sid,
    agent_ctx=ctx,
    current_message=message,
)
```

`build_model_context()` 内部流程：

```text
1. 读取 session.compacted_upto_turn_id
2. 读取最新压缩摘要
3. 读取 cutoff 之后的消息
4. 估算 token
5. 超阈值则调用 maybe_compact()
6. 重新读取压缩后的上下文
7. 返回给 agent.astream()
```

### 重新生成处理

`truncate_last_turn()` 需要处理压缩边界：

- 删除的 turn 大于 cutoff：只删消息，不动 compaction。
- 删除的 turn 小于等于 cutoff：拒绝重新生成，提示该轮已被压缩。

### 压缩摘要的存放方式

不要把压缩摘要作为 `role='system'` 存进 `chat_messages`，因为 `ModelAgent.astream()` 会丢弃历史里的 SystemMessage 并重新注入系统提示词。

推荐方式：

- 压缩摘要存在 `chat_compactions`。
- `load_model_history()` 在返回历史时把摘要作为上下文消息插入。

### 验收

- 正常对话无明显变化。
- 长会话触发压缩后，模型仍能回答之前的事实。
- 前端历史展示不丢消息。
- 重新生成不会破坏压缩边界。

---

## 8. Phase 4：上下文分段抽象

目标：为下列内容提供统一位置，但不和压缩摘要混在一起：

- `Skills Snapshot`
- `Soul`
- `Identity`
- `User Profile`
- `Agents Guide`
- `Long-term Memory`

### 最终结构

采用“agent 决定要什么，用户内容按 user 隔离”的三层结构：

```text
agent_context_bindings   # agent 的绑定 / 策略：顺序、预算、信任级别、引用谁
agent_context_docs       # agent 拥有的内容；agent_id=NULL 表示全局共享
user_context_docs        # user 拥有的内容；按 user_id 隔离
```

`agent_memories` 仍属于 Phase 5，不在 Phase 4 建表。

### `agent_context_bindings`

```text
id
agent_id
key                 # soul / identity / agents_guide / skills_snapshot / user_profile / long_term_memory
title
resolver            # agent_doc / user_doc / generated / memory / none
ref_key             # 指向 agent doc key / user doc key / 生成器名
enabled
priority
max_tokens
trust_level         # policy / data / generated
created_at / updated_at
```

这张表只声明“要注入什么、按什么顺序、最多多少 token、如何信任”，不保存实际内容。

### `agent_context_docs`

```text
id
agent_id            # NULL 表示全局共享，例如全站 AGENTS.md
key
title
content
version_hash
created_at / updated_at
```

用于：

- `Soul`
- `Identity`
- `Agents Guide`
- 其他 agent 级或全局规则文本

### `user_context_docs`

```text
id
user_id
key                 # user_profile / preferences / project_background ...
title
content
version_hash
created_at / updated_at
```

用于：

- `USER.md`
- 用户偏好
- 用户背景

约束：`UNIQUE(user_id, key)`。这张表不包含 `agent_id`，避免把用户数据变成 agent 的私有财产。

### 各段归属

| 段 | resolver | 内容存储 |
|---|---|---|
| Skills Snapshot | `generated` | 不落库正文，按工具注册表实时生成 |
| Soul | `agent_doc` | `agent_context_docs` |
| Identity | `agent_doc` | `agent_context_docs` |
| Agents Guide | `agent_doc` | `agent_context_docs`（Agent 专属） |
| User Profile | `user_doc` | `user_context_docs` |
| Long-term Memory | `memory` | Phase 5 的 `agent_memories`，当前跳过 |

### 新增模块

```text
backend/app/context/
- models.py       # 三张表 ORM
- schemas.py      # 请求响应模型
- service.py      # CRUD 与内容 hash
- assembler.py    # 按 binding 解析内容、限预算、输出 ContextBundle
- router.py       # 管理接口
```

### 装配流程

```text
读取 agent_context_bindings（enabled，按 priority）
  ├─ agent_doc   → agent_context_docs（agent 专属优先，全局其次）
  ├─ user_doc    → user_context_docs（按 user_id）
  ├─ generated   → build_skills_snapshot()
  ├─ memory      → Phase 5 才实现，当前跳过
  └─ none        → 跳过
```

每段独立截断，全局预算由 `max_context_tokens` 控制。Phase 4 使用字符数粗估 token，Phase 0 完成后替换为 tiktoken / usage 校准。

### 注入方式

`ModelAgent.astream()` 增加参数：

```python
context_messages: Sequence[Any] | None = None
```

内部消息顺序：

```text
SystemMessage(system_prompt)
+ context_messages
+ compacted / recent history
```

### 验收

- agent 配置和用户数据分表，权限与缓存策略分离。
- 每个 agent 可以独立开关上下文段、调整顺序和预算。
- 用户资料缺失时静默跳过，不影响对话。
- Skills Snapshot 自动生成，不需要人工维护。
- Long-term Memory 只保留 binding 位，Phase 5 前不伪造内容。

---

## 9. Phase 5：长期记忆，单独实施

目标：实现跨 session 的结构化事实，不复用压缩摘要表。

### 新增表 `agent_memories`

```text
id
user_id
agent_id
kind            # preference / fact / decision / project
content
importance
pinned
source_session_ids
valid_from
valid_until
created_at
updated_at
```

### 写入时机

- 一轮回答完成后抽取。
- 只抽稳定事实，不抽过程性内容。
- 支持用户手工置顶、删除。

### 读取时机

在 `ContextAssembler` 中按：

```text
pinned 优先 + importance 排序 + 最近使用时间
```

取 top N 注入上下文。

### 验收

- 关闭压缩不影响长期记忆。
- 压缩摘要不会自动写进长期记忆。
- 长期记忆按 agent 隔离。
- 用户可以管理自己的长期记忆。

---

## 10. Phase 6：管理界面

只在 Phase 1～5 稳定后实施。

### Agent 管理页新增

- 上下文窗口大小
- 压缩阈值
- 最近保留轮数
- 上下文段开关
- 长期记忆查看、置顶、删除

### 会话详情新增

- 当前上下文 token
- 是否触发过压缩
- 压缩摘要版本
- 注入了哪些长期记忆

---

## 11. 推荐执行顺序

1. Phase 0：token 计量
2. Phase 1：压缩表结构与历史加载
3. Phase 2：压缩执行器
4. Phase 3：接入 `/chat`
5. Phase 4：agent 上下文段
6. Phase 5：长期记忆
7. Phase 6：管理界面

建议先做到 Phase 3，把「长会话压缩 messages」闭环跑通；长期记忆等压缩稳定后再做，避免两个概念互相污染。
