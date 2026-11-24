/**
 * 设置类接口封装：对接后端 /settings/*（开发环境经 Vite 代理到 FastAPI）
 */

import { ApiError, getToken } from './auth'

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

/** 获取当前登录用户的 LLM 配置 */
export function getLlmProviders(): Promise<LlmProviderDto[]> {
  return llmRequest<LlmProviderDto[]>('/settings/llm')
}

/** 整表替换当前登录用户的 LLM 配置 */
export function putLlmProviders(providers: LlmProviderDto[]): Promise<LlmProviderDto[]> {
  return llmRequest<LlmProviderDto[]>('/settings/llm', {
    method: 'PUT',
    body: JSON.stringify({ providers }),
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
