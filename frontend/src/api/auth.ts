/**
 * 认证接口封装：对接后端 /auth/*（开发环境经 Vite 代理到 auth 微服务 8001）
 *
 * access token 存 localStorage + Bearer；refresh token 由后端下发 HttpOnly Cookie，
 * 前端读不到也无需管理。续期有两条路：
 * 1. 主动：解出 access token 的 exp，在到期前就调 /auth/refresh 换新的（token 保活）；
 * 2. 兜底：携带 access 的请求遇 401 时刷新一次并重试。
 * 走手工 fetch 的流式接口（/chat）不进第 2 条链路，靠第 1 条 + 发送前 ensureFreshToken 兜住。
 */

export interface User {
  id: number
  username: string
  email: string
  nickname: string
  /** 压缩后的图片 data URL；空串表示未设置头像 */
  avatar: string
  is_active: boolean
  /** 仅管理员能配模型密钥（/settings/llm 读写），普通用户只能选模型 */
  is_admin: boolean
  created_at: string
}

export interface Token {
  access_token: string
  token_type: string
  expires_in?: number | null
}

const TOKEN_KEY = 'asksource_token'

/**
 * 提前这么多秒续期（access 有效期 15 分钟）：既要覆盖一次 /auth/refresh 的往返耗时，
 * 也要容得下客户端与服务器的时钟偏差——偏差方向不利时，前端以为还剩一分钟、
 * 服务端其实已经判过期了。
 */
const REFRESH_MARGIN_SECONDS = 120

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  // 新 token 到手就按它的过期时间重排保活
  startTokenKeepAlive()
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  stopTokenKeepAlive()
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

interface RequestOptions extends RequestInit {
  /** 是否注入 Authorization 头（受保护接口用），默认 false */
  withAuth?: boolean
  /** 401 时是否触发自动刷新续期，默认与 withAuth 一致 */
  allowRefresh?: boolean
}

async function rawFetch(path: string, options: RequestInit = {}): Promise<Response> {
  // 注意：options.headers 可能是 Headers 实例，不能用对象展开合并（会丢头）
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  try {
    return await fetch(path, {
      // 携带 /接收 refresh Cookie（同源经 Vite 代理）
      credentials: 'include',
      ...options,
      headers,
    })
  } catch {
    throw new ApiError(0, '无法连接服务器，请确认后端已启动')
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail =
      data && typeof data.detail === 'string' ? data.detail : `请求失败 (${res.status})`
    throw new ApiError(res.status, detail)
  }
  return data as T
}

// 并发 401 共享同一个刷新请求，避免风暴
let refreshPromise: Promise<boolean> | null = null

function doRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = rawFetch('/auth/refresh', { method: 'POST' })
      .then(async (res) => {
        if (!res.ok) return false
        const t = (await res.json()) as Token
        setToken(t.access_token)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

type SessionExpiredListener = () => void
const sessionExpiredListeners = new Set<SessionExpiredListener>()

/**
 * 订阅「续期失败」事件（refresh 也过期或被吊销），返回取消订阅的函数。
 * token 本身的清理由本模块负责，订阅方只需要把用户态作废。
 */
export function onSessionExpired(cb: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(cb)
  return () => {
    sessionExpiredListeners.delete(cb)
  }
}

function notifySessionExpired(): void {
  for (const cb of [...sessionExpiredListeners]) cb()
}

/** 刷新一次；彻底失败则清掉本地 access 并通知订阅方会话已结束 */
async function refreshOrGiveUp(): Promise<boolean> {
  const before = getToken()
  if (await doRefresh()) return true
  // refresh token 是一次性轮换的：多标签页里另一个页可能刚好抢先刷成功，
  // 它会把新 access 写进 localStorage，回读一下就能复用，别把用户踢成未登录
  await new Promise((resolve) => setTimeout(resolve, 250))
  const current = getToken()
  if (current && current !== before) return true
  clearToken()
  notifySessionExpired()
  return false
}

/** 强制刷新（不看剩余时间），供「已经吃到 401」的链路用 */
export function forceRefreshToken(): Promise<boolean> {
  return refreshOrGiveUp()
}

/**
 * 从 JWT 第二段解出 exp（秒级时间戳）。
 * 只解码不验签——验签是后端的事，前端需要的仅是过期时间。
 */
function readTokenExpSeconds(token: string): number | null {
  const payload = token.split('.')[1]
  if (!payload) return null
  try {
    // JWT 用 base64url，atob 只认标准 base64；且缺 padding 时长度 % 4 == 1 会抛，先补齐
    const b64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const claims = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof claims.exp === 'number' ? claims.exp : null
  } catch {
    // 不是标准 JWT：不做预刷新，真正的过期交给 401 兜底
    return null
  }
}

/** access token 剩余秒数：未登录返回 0，解不出过期时间返回 null */
export function tokenRemainingSeconds(): number | null {
  const token = getToken()
  if (!token) return 0
  const exp = readTokenExpSeconds(token)
  if (exp === null) return null
  return exp - Math.floor(Date.now() / 1000)
}

/**
 * 快要到期就先续期，返回「现在能不能直接拿 token 去发请求」。
 * 未登录时直接返回 false 且不打 /auth/refresh（没有 Cookie 可刷，纯属空跑）。
 */
export async function ensureFreshToken(): Promise<boolean> {
  if (!getToken()) return false
  const remaining = tokenRemainingSeconds()
  if (remaining === null) return true
  if (remaining > REFRESH_MARGIN_SECONDS) return true
  return refreshOrGiveUp()
}

let keepAliveTimer: ReturnType<typeof setTimeout> | null = null
let keepAliveListening = false

/** 按当前 token 的过期时间重排一次唤醒（带抖动，见下） */
function scheduleKeepAlive(): void {
  if (typeof window === 'undefined') return
  const remaining = tokenRemainingSeconds()
  if (remaining === null) return
  // 多个标签页的 token 同时到期，定时器会在同一毫秒集体醒来抢着刷新；
  // 加 0~30s 抖动把唤醒时刻错开，配合 refreshOrGiveUp 的回读基本消除碰撞
  const jitter = Math.random() * 30
  const delay = Math.max((remaining - REFRESH_MARGIN_SECONDS - jitter) * 1000, 1000)
  if (keepAliveTimer) clearTimeout(keepAliveTimer)
  keepAliveTimer = setTimeout(() => void keepAliveTick(), delay)
}

async function keepAliveTick(): Promise<void> {
  keepAliveTimer = null
  if (!getToken()) return
  await ensureFreshToken()
  // 续期失败时 refreshOrGiveUp 已 clearToken（顺带 stopTokenKeepAlive），这里不再空转重试
  if (getToken()) scheduleKeepAlive()
}

/** 事件补检：先取消还在排的定时器，否则 tick 会把它的句柄弄丢而叠出多个定时器 */
function keepAliveNow(): void {
  if (keepAliveTimer) {
    clearTimeout(keepAliveTimer)
    keepAliveTimer = null
  }
  void keepAliveTick()
}

/** 开始盯过期时间（幂等）：登录走 setToken 会自动启动，刷新页面后需要显式调一次 */
export function startTokenKeepAlive(): void {
  if (typeof window === 'undefined') return
  if (!keepAliveListening) {
    // 后台标签页的 setTimeout 会被节流到分钟级甚至更久，回到前台必须立刻补一次检查
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') keepAliveNow()
    })
    window.addEventListener('focus', keepAliveNow)
    keepAliveListening = true
  }
  if (getToken()) scheduleKeepAlive()
}

/** 停止保活（登出 / token 被清时由 clearToken 触发；监听器保留，tick 里会自己判空） */
export function stopTokenKeepAlive(): void {
  if (keepAliveTimer) {
    clearTimeout(keepAliveTimer)
    keepAliveTimer = null
  }
}

/** 通用请求：withAuth 时自动带 Bearer；发前先按需续期，遇 401 再刷新一次并重试 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { withAuth = false, allowRefresh, ...init } = options
  const doFetch = () => {
    const headers = new Headers(init.headers)
    if (withAuth) {
      const token = getToken()
      if (token) headers.set('Authorization', `Bearer ${token}`)
    }
    return rawFetch(path, { ...init, headers })
  }

  // 提前续期：还有一大截寿命时这里是个空操作，只省下真正到期时那一趟 401 + 重试
  if (withAuth) await ensureFreshToken()

  let res = await doFetch()
  const shouldRefresh = allowRefresh ?? withAuth
  if (res.status === 401 && withAuth && shouldRefresh && getToken()) {
    if (await refreshOrGiveUp()) res = await doFetch()
  }
  return parse<T>(res)
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
  return request<User>('/auth/me', { withAuth: true })
}

/** 修改昵称 / 头像（未提交的字段保持不变） */
export function updateProfile(payload: { nickname?: string; avatar?: string }) {
  return request<User>('/auth/me', {
    method: 'PATCH',
    withAuth: true,
    body: JSON.stringify(payload),
  })
}

/** 修改密码：成功后服务端的 refresh 全部吊销，前端应回到登录态 */
export function changePassword(payload: { old_password: string; new_password: string }) {
  return request<{ message: string }>('/auth/password', {
    method: 'POST',
    withAuth: true,
    body: JSON.stringify(payload),
  })
}

/** 登出：吊销服务端 refresh（后端清 Cookie），失败静默 */
export async function logoutApi(): Promise<void> {
  try {
    await rawFetch('/auth/logout', { method: 'POST' })
  } catch {
    // 网络/服务异常不阻断前端登出流程
  }
}
