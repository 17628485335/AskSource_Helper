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

/** 与后端 MessageOut 对齐（role 含 user/assistant/system/tools） */
export interface SessionMessageDto {
  id: number
  session_id: number
  role: string
  content: string
  tool_name: string
  tokens: number
  created_at: string
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
