/**
 * 对话状态存储（组合式单例）
 *
 * 持有消息列表、会话 id 与流式状态；把 SSE 事件合并进「当前正在流式的那条助手气泡」。
 * 只负责状态迁移，不关心渲染与滚动（那部分在 HomeStage 里）。
 */

import { computed, ref } from 'vue'
import { streamChat, type ChatCitation, type ChatEvent, type ChatPayload } from '../api/chat'
import { listSessionMessages } from '../api/session'

/** 一次工具调用（协议 v2 按 call_id 跟踪）：并行同名调用各自一条 */
export interface ToolCall {
  /** 模型侧 tool_call_id；个别上游不返回时为空，配对退化到按 name */
  callId: string
  name: string
  input: Record<string, unknown>
  state: 'running' | 'done'
  /** 该次工具调用产生的引用（网页搜索完成后可据此展示站点图标与标题） */
  citations: ChatCitation[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** 本轮的工具调用（按出现顺序，以 call_id 去重）：徽标据此逐个渲染 */
  toolCalls: ToolCall[]
  /** 本轮工具返回的来源列表（按 [n] 编号升序）；历史会话从 tool_calls.citations_json 重建 */
  citations: ChatCitation[]
  /** 助手气泡是否还在接收增量 */
  streaming: boolean
  /** 本轮失败原因（含后端 error 事件与 fetch / 解析异常） */
  error: string
  /** 深度思考过程（仅本轮流式期间展示；后端不落库，重进会话为空） */
  reasoning: string
  /** 本轮实际生效的档位（由 meta 事件回填），等待提示据此措辞 */
  thinking: boolean
  /** 消息产生时刻（ISO）：本地发送取当前时间，历史恢复取后端落库时间 */
  created_at: string
}

type Options = Pick<
  ChatPayload,
  'platform' | 'model' | 'thinking' | 'workspace_id' | 'regenerate' | 'agent_key'
>

const messages = ref<ChatMessage[]>([])
const busy = ref(false)
const sessionId = ref<number | null>(null)
/** meta 事件带回的模型标识，用于在会话顶部展示 */
const modelLabel = ref('')
/** meta 事件带回的 agent 与提示词版本，用于会话详情展示 */
const agentKey = ref('')
const promptVersion = ref<number | null>(null)
/** 本轮请求发起时刻（0 = 空闲），供 UI 计算已等待秒数 */
const startedAt = ref(0)

let controller: AbortController | null = null

const hasConversation = computed(() => messages.value.length > 0)

/** 后端 citations_json 的条目做一次收敛，避免历史/实时两条路径字段处理不一致 */
function normalizeCitation(raw: Partial<ChatCitation>): ChatCitation | null {
  if (typeof raw.index !== 'number') return null
  return {
    index: raw.index,
    title: typeof raw.title === 'string' ? raw.title : '',
    url: typeof raw.url === 'string' ? raw.url : '',
    snippet: typeof raw.snippet === 'string' ? raw.snippet : '',
    published_date: typeof raw.published_date === 'string' ? raw.published_date : '',
    kind: typeof raw.kind === 'string' ? raw.kind : '',
  }
}

/** 新建一条气泡：字段集中在这里，避开新增状态时某处漏填 */
function newMessage(
  role: ChatMessage['role'],
  content: string,
  created_at = new Date().toISOString(),
): ChatMessage {
  return {
    role,
    content,
    toolCalls: [],
    citations: [],
    streaming: false,
    error: '',
    reasoning: '',
    thinking: false,
    created_at,
  }
}

function applyEvent(event: ChatEvent, bubble: ChatMessage) {
  switch (event.type) {
    case 'meta':
      sessionId.value = event.session_id
      // 档位以服务端回写为准：模型不支持时后端会按快速发，本地选择只是意向
      bubble.thinking = event.thinking
      modelLabel.value = `${event.platform} / ${event.model}${event.thinking ? ' · 深度' : ''}`
      agentKey.value = event.agent_key ?? ''
      promptVersion.value = event.prompt_version ?? null
      break
    case 'segment_start':
      // 后端分段落库用的边界；前端仍用一个气泡展示整轮回答，这里无需改状态
      break
    case 'token':
      bubble.content += event.text
      break
    case 'reasoning':
      bubble.reasoning += event.text
      break
    case 'tool_start': {
      // 以 call_id 为主键（并行同名才能各亮一枚），个别上游无 id 时回退工具名
      const key = event.call_id || event.tool
      if (!bubble.toolCalls.some((c) => (c.callId || c.name) === key)) {
        bubble.toolCalls.push({
          callId: event.call_id,
          name: event.tool,
          input: event.input,
          state: 'running',
          citations: [],
        })
      }
      break
    }
    case 'tool_end': {
      // 乱序容错：没收到 start（理论上不会）也补一条再翻状态
      const key = event.call_id || event.tool
      const call = bubble.toolCalls.find((c) => (c.callId || c.name) === key)
      if (call) call.state = 'done'
      else
        bubble.toolCalls.push({
          callId: event.call_id,
          name: event.tool,
          input: {},
          state: 'done',
          citations: [],
        })
      break
    }
    case 'citations':
      // 一次工具调用一帧，多轮搜索累加；编号由后端从本轮已用号后续，所以按 index 去重而不是 url
      // （同一个地址被搜到一次、又被 read_url 打开一次时，两条正文不同、[n] 也不同）
      const callKey = event.call_id || event.tool
      const call = bubble.toolCalls.find((c) => (c.callId || c.name) === callKey)
      for (const item of event.items) {
        if (!bubble.citations.some((c) => c.index === item.index)) bubble.citations.push(item)
        if (call && !call.citations.some((c) => c.index === item.index)) call.citations.push(item)
      }
      bubble.citations.sort((a, b) => a.index - b.index)
      if (call) call.citations.sort((a, b) => a.index - b.index)
      break
    case 'done':
      // 正常情况下增量已拼好；done 兜底（例如增量丢失但整段返回）
      if (!bubble.content) bubble.content = event.content
      bubble.streaming = false
      break
    case 'error':
      bubble.error = event.message
      bubble.streaming = false
      break
  }
}

/** 发送一条消息并流式接收；同一时刻只允许一条进行中的流 */
async function send(text: string, options: Options = {}): Promise<void> {
  const content = text.trim()
  if (!content || busy.value) return

  busy.value = true
  startedAt.value = Date.now()
  messages.value.push(newMessage('user', content))

  const placeholder = newMessage('assistant', '')
  placeholder.streaming = true
  messages.value.push(placeholder)
  // 必须取数组里的响应式代理再改动它：直接改 placeholder（原始对象）不会触发视图更新
  const bubble = messages.value[messages.value.length - 1]

  controller = new AbortController()
  try {
    await streamChat(
      { message: content, session_id: sessionId.value, ...options },
      (event) => applyEvent(event, bubble),
      controller.signal,
    )
  } catch (e) {
    bubble.error = e instanceof Error ? e.message : '对话失败'
  } finally {
    bubble.streaming = false
    busy.value = false
    controller = null
  }
}

/** 中止当前流式请求（已生成的文本保留） */
function stop() {
  controller?.abort()
}

/** 打开一个已落库的会话：拉取历史消息映射成气泡列表（tools 角色跳过，与后端 load_history 一致） */
async function loadSession(
  id: number,
  meta?: { platform?: string; model?: string; thinking?: boolean },
): Promise<void> {
  stop() // 若上一条流还在跑先断掉，避免旧增量写进恢复后的气泡
  const rows = await listSessionMessages(id)
  messages.value = rows
    .filter((r) => r.role === 'user' || r.role === 'assistant')
    .map((r) => {
      const msg = newMessage(r.role as 'user' | 'assistant', r.content, r.created_at)
      if (r.role === 'assistant') {
        // 历史会话的工具调用与引用都来自 chat_tool_calls；按 [n] 去重，与实时流一致
        const seen = new Set<number>()
        for (const tc of r.tool_calls ?? []) {
          const callCitations: ChatCitation[] = []
          for (const raw of tc.citations_json ?? []) {
            const item = normalizeCitation(raw as Partial<ChatCitation>)
            if (!item) continue
            callCitations.push(item)
            if (seen.has(item.index)) continue
            seen.add(item.index)
            msg.citations.push(item)
          }
          msg.toolCalls.push({
            callId: tc.call_id,
            name: tc.tool_name,
            input: (tc.input_json as Record<string, unknown>) ?? {},
            state: 'done',
            citations: callCitations.sort((a, b) => a.index - b.index),
          })
        }
        msg.citations.sort((a, b) => a.index - b.index)
      }
      return msg
    })
  sessionId.value = id
  modelLabel.value = meta?.platform
    ? `${meta.platform} / ${meta.model}${meta.thinking ? ' · 深度' : ''}`
    : '历史会话'
  startedAt.value = 0
}

/** 开启新对话：断开旧流并清空本地状态（后端会话仍在，可从历史列表恢复） */
function reset() {
  stop()
  messages.value = []
  sessionId.value = null
  modelLabel.value = ''
  agentKey.value = ''
  promptVersion.value = null
  startedAt.value = 0
}

export function useChat() {
  return {
    messages,
    busy,
    sessionId,
    modelLabel,
    agentKey,
    promptVersion,
    startedAt,
    hasConversation,
    send,
    stop,
    reset,
    loadSession,
  }
}
