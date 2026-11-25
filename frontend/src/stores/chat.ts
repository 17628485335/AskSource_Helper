/**
 * 对话状态存储（组合式单例）
 *
 * 持有消息列表、会话 id 与流式状态；把 SSE 事件合并进「当前正在流式的那条助手气泡」。
 * 只负责状态迁移，不关心渲染与滚动（那部分在 HomeStage 里）。
 */

import { computed, ref } from 'vue'
import { streamChat, type ChatCitation, type ChatEvent, type ChatPayload } from '../api/chat'
import { listSessionMessages } from '../api/session'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** 本轮调用过的工具名（按出现顺序去重） */
  tools: string[]
  /** 工具执行状态（协议 v2 的 tool_start/tool_end）：running 等结束帧翻成 done；
   * 历史恢复时为空，此时徽标不区分状态 */
  toolStates: Record<string, 'running' | 'done'>
  /** 本轮工具返回的来源列表（按 [n] 编号升序）；后端不落库，重进会话为空 */
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

type Options = Pick<ChatPayload, 'platform' | 'model' | 'thinking' | 'workspace_id' | 'regenerate'>

const messages = ref<ChatMessage[]>([])
const busy = ref(false)
const sessionId = ref<number | null>(null)
/** meta 事件带回的模型标识，用于在会话顶部展示 */
const modelLabel = ref('')
/** 本轮请求发起时刻（0 = 空闲），供 UI 计算已等待秒数 */
const startedAt = ref(0)

let controller: AbortController | null = null

const hasConversation = computed(() => messages.value.length > 0)

/** 新建一条气泡：字段集中在这里，避开新增状态时某处漏填 */
function newMessage(
  role: ChatMessage['role'],
  content: string,
  created_at = new Date().toISOString(),
): ChatMessage {
  return {
    role,
    content,
    tools: [],
    toolStates: {},
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
      break
    case 'token':
      bubble.content += event.text
      break
    case 'reasoning':
      bubble.reasoning += event.text
      break
    case 'tool_start':
      if (!bubble.tools.includes(event.tool)) {
        bubble.tools.push(event.tool)
        bubble.toolStates[event.tool] = 'running'
      }
      break
    case 'tool_end':
      // 乱序容错：没收到 start（理论上不会）也补进列表再翻状态
      if (!bubble.tools.includes(event.tool)) bubble.tools.push(event.tool)
      bubble.toolStates[event.tool] = 'done'
      break
    case 'citations':
      // 一次工具调用一帧，多轮搜索累加；编号由后端从本轮已用号后续，所以按 index 去重而不是 url
      // （同一个地址被搜到一次、又被 read_url 打开一次时，两条正文不同、[n] 也不同）
      for (const item of event.items) {
        if (!bubble.citations.some((c) => c.index === item.index)) bubble.citations.push(item)
      }
      bubble.citations.sort((a, b) => a.index - b.index)
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
    .map((r) => newMessage(r.role as 'user' | 'assistant', r.content, r.created_at))
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
  startedAt.value = 0
}

export function useChat() {
  return {
    messages,
    busy,
    sessionId,
    modelLabel,
    startedAt,
    hasConversation,
    send,
    stop,
    reset,
    loadSession,
  }
}
