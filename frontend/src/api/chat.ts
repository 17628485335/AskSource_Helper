/**
 * 流式对话接口：POST /chat，用 fetch + ReadableStream 手工解析 SSE
 *
 * 不用 EventSource，因为它是 GET-only 且不支持请求体；
 * 帧之间以空行分隔，所以必须处理「一帧被拆到两个 chunk」和「一个 chunk 含多帧」。
 */

import { ApiError, ensureFreshToken, forceRefreshToken, getToken } from './auth'

export interface ChatMetaEvent {
  type: 'meta'
  session_id: number
  platform: string
  model: string
  thinking: boolean
}
/** 正文增量（协议 v2：原 delta 改名 token）：拼进回答正文，也进后端落库 buffer */
export interface ChatTokenEvent {
  type: 'token'
  text: string
}
/** 思考增量（仅深度档）：与正文分开下发，不进回答也不落库 */
export interface ChatReasoningEvent {
  type: 'reasoning'
  text: string
}
/** 工具开始执行：模型流里一出现工具名就发（早于真正执行，徽标能提前亮） */
export interface ChatToolStartEvent {
  type: 'tool_start'
  tool: string
  input: Record<string, unknown>
}
/** 工具执行完成：preview 是结果摘要（后端截断），供 tooltip/展开查看 */
export interface ChatToolEndEvent {
  type: 'tool_end'
  tool: string
  preview: string
}
/** 一条引用：来自工具的结构化 artifact，index 就是回答正文里的 [n] */
export interface ChatCitation {
  index: number
  title: string
  url: string
  snippet: string
  published_date: string
  /** search：搜索结果；page：read_url 打开过的页面 */
  kind: string
}
/** 工具返回的引用列表：一次工具调用一帧，与正文分开下发，后端不落库 */
export interface ChatCitationsEvent {
  type: 'citations'
  tool: string
  items: ChatCitation[]
}
export interface ChatDoneEvent {
  type: 'done'
  session_id: number
  content: string
}
export interface ChatErrorEvent {
  type: 'error'
  message: string
}

export type ChatEvent =
  | ChatMetaEvent
  | ChatTokenEvent
  | ChatReasoningEvent
  | ChatToolStartEvent
  | ChatToolEndEvent
  | ChatCitationsEvent
  | ChatDoneEvent
  | ChatErrorEvent

export interface ChatPayload {
  message: string
  session_id?: number | null
  platform?: string
  model?: string
  thinking?: boolean | null
  /** 仅新建会话时生效：新会话归入的工作区，留空后端自动归默认区 */
  workspace_id?: number | null
  /** 重新生成：后端先删掉本轮（末条 user 及其后续回答）再追加本次提问 */
  regenerate?: boolean
}

const CR = String.fromCharCode(13)
const LF = String.fromCharCode(10)

/**
 * SSE 帧分隔符（空行）。服务端一般只发 LF LF，但规范要求兼容 CRLF 与裸 CR，
 * 这里用字符码拼出来，避免源码里的转义序列被工具链当成真实换行处理。
 */
const FRAME_SEP = new RegExp(CR + LF + CR + LF + '|' + LF + LF + '|' + CR + CR)

/** 行分隔符：CRLF 或 LF */
const LINE_SEP = new RegExp(CR + LF + '|' + LF)

function isAbort(e: unknown): boolean {
  return (e as { name?: string })?.name === 'AbortError'
}

/** 解析单帧：只关心 data 字段（后端把事件类型放在 JSON 的 type 里），注释行与 id/retry 忽略 */
function parseFrame(frame: string): ChatEvent | null {
  const dataLines: string[] = []
  for (const line of frame.split(LINE_SEP)) {
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':')
    const field = idx === -1 ? line : line.slice(0, idx)
    // 规范规定冒号后的第一个空格不属于值
    let value = idx === -1 ? '' : line.slice(idx + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'data') dataLines.push(value)
  }
  if (!dataLines.length) return null

  const raw = dataLines.join(LF)
  try {
    const obj = JSON.parse(raw) as ChatEvent
    if (obj && typeof obj.type === 'string') return obj
  } catch {
    /* 落到下面当作错误上报，避免静默丢事件 */
  }
  return { type: 'error', message: `无法解析服务端事件：${raw.slice(0, 120)}` }
}

/**
 * 发起一次流式问答；onEvent 在每收到一个服务端事件时同步调用。
 * 正常结束（收到 done）后 resolve；鉴权失败 / 网络断开时抛 ApiError；主动取消抛 AbortError。
 *
 * /chat 需要读 ReadableStream，用不了 api/auth 的 request()，所以这里自己保证凭证是新的：
 * 发送前先 ensureFreshToken（到期前主动续期），真吃到 401 再刷新一次重发。
 */
export async function streamChat(
  payload: ChatPayload,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const body = JSON.stringify(payload)

  const send = async (): Promise<Response> => {
    const token = getToken()
    try {
      return await fetch('/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body,
        signal,
      })
    } catch (e) {
      if (isAbort(e)) throw e
      throw new ApiError(0, '无法连接服务器，请确认后端已启动')
    }
  }

  await ensureFreshToken()
  let res = await send()
  // 兜底：预检到真正发出之间 token 可能被换掉（别的标签页登出、后端轮换密钥），
  // getToken() 为空说明上面的预检已判定会话结束，不再重复刷一次
  if (res.status === 401 && getToken() && (await forceRefreshToken())) res = await send()

  if (!res.ok) {
    let detail = `请求失败 (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* 响应体不是 JSON，保留状态码文案 */
    }
    if (res.status === 401) detail = '未登录或登录已失效，请先登录'
    throw new ApiError(res.status, detail)
  }
  if (!res.body) throw new ApiError(res.status, '当前浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  /** 消费缓冲区里所有完整帧；残留的半个帧留在 buffer 等下一个 chunk */
  const drain = () => {
    for (;;) {
      const m = FRAME_SEP.exec(buffer)
      if (!m) break
      const event = parseFrame(buffer.slice(0, m.index))
      buffer = buffer.slice(m.index + m[0].length)
      if (event) onEvent(event)
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      drain()
    }
    // 收尾：flush 可能残留的多字节尾巴，并处理末尾没有空行的最后一帧
    buffer += decoder.decode()
    drain()
    const tail = parseFrame(buffer)
    if (tail) onEvent(tail)
  } catch (e) {
    if (isAbort(e)) throw e
    throw new ApiError(0, e instanceof Error ? e.message : '流式连接中断')
  } finally {
    try {
      await reader.cancel()
    } catch {
      /* 流已关闭 */
    }
    reader.releaseLock()
  }
}
