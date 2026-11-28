/**
 * 会话接口封装：对接后端 /sessions/*（app/session 模块）
 *
 * 同样复用 auth.ts 的 request；列表接口用于工作区下的会话展示，
 * 消息接口用于「继续历史对话」时把落库的消息拉回聊天区。
 */

import { request } from './auth'

/** 与后端 app/session/schemas.py SessionOut 对齐 */
export interface SessionDto {
  id: number
  title: string
  workspace_id: number | null
  platform: string
  model: string
  thinking: boolean
  status: string
  message_count: number
  created_at: string
  updated_at: string
}

/** 与后端 ToolCallOut 对齐 */
export interface ToolCallDto {
  id: number
  session_id: number
  message_id: number
  seq: number
  tool_name: string
  call_id: string
  created_at: string
  turn_id?: number | null
  segment_id?: number | null
  input_json?: Record<string, unknown> | null
  result_text?: string
  preview?: string
  duration_ms?: number | null
  citations_json?: Array<Record<string, unknown>> | null
}

/** 消息所属轮次的 token 用量（来自 chat_turns） */
export interface TurnUsageDto {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  /** 最后一次模型调用的 input tokens；与 input_token_details 同口径，用于算缓存命中率 */
  last_input_tokens: number
  input_token_details: Record<string, number>
  output_token_details: Record<string, number>
  model_calls: number
}

/** 与后端 MessageOut 对齐（role 含 user/assistant/system/tools） */
export interface SessionMessageDto {
  id: number
  session_id: number
  role: string
  content: string
  tool_name: string
  tokens: number
  created_at: string
  turn_id?: number | null
  tool_calls?: ToolCallDto[]
  turn_usage?: TurnUsageDto | null
}

/** 与后端 ContextUsageOut 对齐 */
export interface ContextUsageDto {
  used_tokens: number
  context_size: number
  remaining_tokens: number
  usage_ratio: number
  message_count: number
  summary_chars: number
  /** used_tokens 的来源：api=上游真实 usage，estimated=tiktoken 估算 */
  source: string
}

export interface SessionPageDto {
  items: SessionDto[]
  total: number
  limit: number
  offset: number
}

/** 会话列表；workspace_id 非空时只取该工作区下的会话 */
export function listSessions(params: {
  workspace_id?: number | null
  limit?: number
  offset?: number
  status?: 'active' | 'archived' | 'all'
  keyword?: string
} = {}): Promise<SessionPageDto> {
  const q = new URLSearchParams()
  if (params.workspace_id) q.set('workspace_id', String(params.workspace_id))
  q.set('limit', String(params.limit ?? 20))
  if (params.offset) q.set('offset', String(params.offset))
  q.set('status', params.status ?? 'active')
  if (params.keyword) q.set('keyword', params.keyword)
  return request<SessionPageDto>(`/sessions?${q.toString()}`, { withAuth: true })
}

/** 取会话内最近的消息（默认 200 条封顶，足够恢复一场对话） */
export function listSessionMessages(
  sessionId: number,
  limit = 200,
): Promise<SessionMessageDto[]> {
  return request<SessionMessageDto[]>(`/sessions/${sessionId}/messages?limit=${limit}`, {
    withAuth: true,
  })
}

/** 查询会话上下文用量；contextSize 由当前选中模型提供 */
export function getContextUsage(sessionId: number, contextSize: number): Promise<ContextUsageDto> {
  return request<ContextUsageDto>(
    `/sessions/${sessionId}/context-usage?context_size=${contextSize}`,
    { withAuth: true },
  )
}

/** 手动压缩更早轮次；返回压缩后的上下文用量，省掉前端二次拉取 */
export function compactSessionHistory(
  sessionId: number,
  contextSize: number,
): Promise<ContextUsageDto> {
  return request<ContextUsageDto>(
    `/sessions/${sessionId}/compact?context_size=${contextSize}`,
    { withAuth: true, method: 'POST' },
  )
}
