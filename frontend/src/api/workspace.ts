/**
 * 工作区接口封装：对接后端 /workspaces/*（app/workspace 模块）
 *
 * 复用 auth.ts 的 request：自动带 Bearer，401 时静默刷新并重试一次。
 */

import { request } from './auth'

/** 与后端 app/workspace/schemas.py WorkspaceOut 对齐 */
export interface WorkspaceDto {
  id: number
  name: string
  description: string
  is_default: boolean
  session_count: number
  created_at: string
  updated_at: string
}

/** 列表；后端会在用户首个工作区不存在时自动初始化「个人空间」 */
export function listWorkspaces(): Promise<WorkspaceDto[]> {
  return request<WorkspaceDto[]>('/workspaces', { withAuth: true })
}

export function createWorkspace(payload: { name: string; description?: string }): Promise<WorkspaceDto> {
  return request<WorkspaceDto>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
    withAuth: true,
  })
}

export function updateWorkspace(
  id: number,
  payload: { name?: string; description?: string },
): Promise<WorkspaceDto> {
  return request<WorkspaceDto>(`/workspaces/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
    withAuth: true,
  })
}

/** 删除工作区；其下会话解挂回未归属（后端置 workspace_id=NULL） */
export function deleteWorkspace(id: number): Promise<void> {
  return request<void>(`/workspaces/${id}`, { method: 'DELETE', withAuth: true })
}
