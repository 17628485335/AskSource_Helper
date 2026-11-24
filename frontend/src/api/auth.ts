/**
 * 认证接口封装：对接后端 /auth/*（开发环境经 Vite 代理到 FastAPI）
 */

export interface User {
  id: number
  username: string
  email: string
  is_active: boolean
  created_at: string
}

export interface Token {
  access_token: string
  token_type: string
}

const TOKEN_KEY = 'asksource_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** 携带 HTTP 状态码的错误，message 取自后端 detail 字段 */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
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

export function register(payload: {
  username: string
  email: string
  password: string
}) {
  return request<User>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function login(payload: { account: string; password: string }) {
  return request<Token>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getMe(): Promise<User> {
  const token = getToken()
  return request<User>('/auth/me', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}
