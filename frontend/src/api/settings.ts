/**
 * 设置类接口封装：对接后端 /settings/*（开发环境经 Vite 代理到 FastAPI）
 */

import { ApiError, ensureFreshToken, getToken, request } from './auth'

export interface ModelProviderOption {
  value: string
  label: string
  base_url: string
}

/** LLM 提供商配置（与后端 app/settings/schemas.py ProviderOut/Write 对齐） */
export interface LlmProviderDto {
  id?: number
  platform: string
  name: string
  base_url: string
  api_key: string
  default_model: string
  supports_thinking: boolean
  is_active: boolean
}

/** 获取「模型提供商」下拉选项（阿里百炼 / DeepSeek / 硅基流动） */
export async function getModelProviders(): Promise<ModelProviderOption[]> {
  let res: Response
  try {
    res = await fetch('/settings/model-providers')
  } catch {
    throw new Error('无法连接服务器，请确认后端已启动')
  }
  if (!res.ok) {
    throw new Error(`获取模型提供商失败 (${res.status})`)
  }
  return res.json() as Promise<ModelProviderOption[]>
}

/** 携带 JWT 的 /settings/llm 请求；错误以 ApiError 抛出 */
async function llmRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  // 同样是手写 fetch，不进 request() 的 401 重试链路，发之前先确保 token 没到期
  await ensureFreshToken()
  const token = getToken()
  let res: Response
  try {
    res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    })
  } catch {
    throw new ApiError(0, '无法连接服务器，请确认后端已启动')
  }
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail =
      data && typeof data.detail === 'string' ? data.detail : `请求失败 (${res.status})`
    throw new ApiError(res.status, detail)
  }
  return data as T
}

/** 获取全局 LLM 配置（含 api_key，仅管理员；普通用户会得到 403） */
export function getLlmProviders(): Promise<LlmProviderDto[]> {
  return llmRequest<LlmProviderDto[]>('/settings/llm')
}

/** 整表替换全局 LLM 配置（仅管理员：这张表影响所有用户的对话） */
export function putLlmProviders(providers: LlmProviderDto[]): Promise<LlmProviderDto[]> {
  return llmRequest<LlmProviderDto[]>('/settings/llm', {
    method: 'PUT',
    body: JSON.stringify({ providers }),
  })
}

/** 对话框可选的模型（后端 /settings/models：登录即可读，响应里不含密钥） */
export interface ChatModelOption {
  platform: string
  platform_label: string
  model: string
  name: string
  supports_thinking: boolean
  is_active: boolean
  /** 该行是否真的建进了模型池；false 表示配置还在表里但构建失败，下拉里该置灰 */
  available: boolean
  /** available 为 false 时的原因，给标题提示用 */
  unavailable_reason: string
}

/** 拉取对话可选的模型列表 */
export function getChatModels(): Promise<ChatModelOption[]> {
  return llmRequest<ChatModelOption[]>('/settings/models')
}

/** 当前真正挂进模型池的工具（后端 /settings/tools：登录即可读） */
export interface ToolDto {
  name: string
  /** 注册时声明的中文展示名，侧边栏显示它 */
  label: string
  /** lucide 图标名，前端按名取内联 SVG */
  icon: string
}

/** 侧边栏「工具」悬停面板用：只列当前可用工具 */
export function listTools(): Promise<ToolDto[]> {
  return request<ToolDto[]>('/settings/tools', { withAuth: true })
}

/* ---------------- Agent 定义与提示词版本 ---------------- */

export interface AgentDto {
  id: number
  agent_key: string
  name: string
  description: string
  platform: string
  model: string
  thinking: boolean
  /** null=全部工具，[]=禁用所有工具；列表来自 readonly 响应式副本 */
  tool_names: readonly string[] | null
  active_prompt_version: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AgentPromptDto {
  id: number
  agent_id: number
  version: number
  system_prompt: string
  note: string
  created_at: string
}

export interface AgentCreatePayload {
  agent_key: string
  name?: string
  description?: string
  platform?: string
  model?: string
  thinking?: boolean
  tool_names?: string[] | null
  system_prompt?: string
}

export interface AgentUpdatePayload {
  name?: string
  description?: string
  platform?: string
  model?: string
  thinking?: boolean
  tool_names?: string[] | null
  active_prompt_version?: number
  is_active?: boolean
}

export interface AgentPromptCreatePayload {
  system_prompt: string
  note?: string
  activate?: boolean
}

const jsonBody = (payload: unknown): string => JSON.stringify(payload)

export function listAgents(includeInactive = false): Promise<AgentDto[]> {
  return request<AgentDto[]>(`/agents?include_inactive=${includeInactive}`, { withAuth: true })
}

export function createAgent(payload: AgentCreatePayload): Promise<AgentDto> {
  return request<AgentDto>('/agents', {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function updateAgent(id: number, payload: AgentUpdatePayload): Promise<AgentDto> {
  return request<AgentDto>(`/agents/${id}`, {
    method: 'PATCH',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function deleteAgent(id: number): Promise<void> {
  return request<void>(`/agents/${id}`, { method: 'DELETE', withAuth: true })
}

export function listAgentPrompts(id: number): Promise<AgentPromptDto[]> {
  return request<AgentPromptDto[]>(`/agents/${id}/prompts`, { withAuth: true })
}

export function createAgentPrompt(
  id: number,
  payload: AgentPromptCreatePayload,
): Promise<AgentPromptDto> {
  return request<AgentPromptDto>(`/agents/${id}/prompts`, {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function activateAgentPrompt(id: number, version: number): Promise<AgentDto> {
  return request<AgentDto>(`/agents/${id}/prompts/${version}/activate`, {
    method: 'POST',
    withAuth: true,
  })
}

/* ---------------- Agent 上下文分段 ---------------- */

export type ContextResolver = 'agent_doc' | 'user_doc' | 'generated' | 'memory' | 'none'
export type ContextTrustLevel = 'anchor' | 'policy' | 'data' | 'generated'

export interface AgentContextBindingDto {
  id: number
  agent_id: number
  key: string
  title: string
  resolver: ContextResolver
  ref_key: string
  enabled: boolean
  priority: number
  max_tokens: number
  trust_level: ContextTrustLevel
  trust_hint: string
  created_at: string
  updated_at: string
}

export interface AgentContextDocDto {
  id: number
  agent_id: number | null
  key: string
  title: string
  content: string
  version_hash: string
  created_at: string
  updated_at: string
}

export interface AgentContextBindingPayload {
  key: string
  title?: string
  resolver?: ContextResolver
  ref_key?: string
  enabled?: boolean
  priority?: number
  max_tokens?: number
  trust_level?: ContextTrustLevel
  trust_hint?: string
}

export type AgentContextBindingUpdatePayload = Partial<Omit<AgentContextBindingPayload, 'key'>>

export interface AgentContextDocPayload {
  agent_id?: number | null
  key: string
  title?: string
  content?: string
}

export interface AgentContextDocUpdatePayload {
  title?: string
  content?: string
}

export function listAgentBindings(agentId: number): Promise<AgentContextBindingDto[]> {
  return request<AgentContextBindingDto[]>(`/context/agent-bindings?agent_id=${agentId}`, {
    withAuth: true,
  })
}

export function createAgentBinding(
  agentId: number,
  payload: AgentContextBindingPayload,
): Promise<AgentContextBindingDto> {
  return request<AgentContextBindingDto>(`/context/agent-bindings?agent_id=${agentId}`, {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function updateAgentBinding(
  bindingId: number,
  payload: AgentContextBindingUpdatePayload,
): Promise<AgentContextBindingDto> {
  return request<AgentContextBindingDto>(`/context/agent-bindings/${bindingId}`, {
    method: 'PATCH',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function listAgentDocs(
  agentId?: number | null,
  includeGlobal = true,
): Promise<AgentContextDocDto[]> {
  const query = new URLSearchParams()
  if (agentId != null) query.set('agent_id', String(agentId))
  query.set('include_global', String(includeGlobal))
  return request<AgentContextDocDto[]>(`/context/agent-docs?${query.toString()}`, {
    withAuth: true,
  })
}

export function createAgentDoc(payload: AgentContextDocPayload): Promise<AgentContextDocDto> {
  return request<AgentContextDocDto>('/context/agent-docs', {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function updateAgentDoc(
  docId: number,
  payload: AgentContextDocUpdatePayload,
): Promise<AgentContextDocDto> {
  return request<AgentContextDocDto>(`/context/agent-docs/${docId}`, {
    method: 'PATCH',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export type ContextGenerateKind = 'soul' | 'identity' | 'agents_guide' | 'user_profile'

export interface ContextGeneratePayload {
  kind: ContextGenerateKind
  agent_id?: number | null
  current?: string
  hint?: string
  variant?: number
}

export interface ContextGenerateResult {
  content: string
}

/** 调用 LLM 生成上下文段正文；只支持 soul / identity / agents_guide */
export function generateContextContent(
  payload: ContextGeneratePayload,
): Promise<ContextGenerateResult> {
  return request<ContextGenerateResult>('/context/generate', {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

/** 与运行时共用同一套拼装逻辑，生成最终注入模型的系统提示词 */
export function composeSystemPrompt(payload: {
  prompt: string
  agent_id?: number | null
  tool_names?: string[] | null
}): Promise<ContextGenerateResult> {
  return request<ContextGenerateResult>('/context/compose-system-prompt', {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

/* ---------------- Agent 长期记忆 ---------------- */

export interface AgentMemoryDto {
  id: number
  agent_id: number
  content: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export function listAgentMemories(agentId: number): Promise<AgentMemoryDto[]> {
  return request<AgentMemoryDto[]>(`/context/agent-memories?agent_id=${agentId}`, {
    withAuth: true,
  })
}

export function createAgentMemory(agentId: number, content: string): Promise<AgentMemoryDto> {
  return request<AgentMemoryDto>(`/context/agent-memories?agent_id=${agentId}`, {
    method: 'POST',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody({ content }),
  })
}

export function updateAgentMemory(
  agentId: number,
  memoryId: number,
  payload: { content?: string; enabled?: boolean },
): Promise<AgentMemoryDto> {
  return request<AgentMemoryDto>(`/context/agent-memories/${memoryId}?agent_id=${agentId}`, {
    method: 'PATCH',
    withAuth: true,
    headers: { 'Content-Type': 'application/json' },
    body: jsonBody(payload),
  })
}

export function deleteAgentMemory(agentId: number, memoryId: number): Promise<void> {
  return request<void>(`/context/agent-memories/${memoryId}?agent_id=${agentId}`, {
    method: 'DELETE',
    withAuth: true,
  })
}

/** 连通性测试结果（与后端 ProviderTestResult 对齐） */
export interface LlmTestResult {
  ok: boolean
  detail: string
  model_count: number | null
}

/** 用表单草稿值测试提供商连通性 / 密钥有效性（需登录） */
export function testLlmProvider(payload: {
  base_url: string
  api_key: string
  default_model: string
}): Promise<LlmTestResult> {
  return llmRequest<LlmTestResult>('/settings/llm/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
