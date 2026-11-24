/**
 * 设置类接口封装：对接后端 /settings/*（开发环境经 Vite 代理到 FastAPI）
 */

import { ApiError, ensureFreshToken, getToken } from './auth'

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
