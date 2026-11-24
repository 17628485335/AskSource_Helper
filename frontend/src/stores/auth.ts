/**
 * 认证状态存储（组合式单例）

 * 持有当前用户、加载态与错误信息，封装登录 / 注册 / 退出 / 恢复会话流程。
 * Token 由 api/auth 统一管理（localStorage），本层只关心用户态。
 */

import { computed, readonly, ref } from 'vue'
import * as authApi from '../api/auth'
import type { User } from '../api/auth'

const user = ref<User | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const isLoggedIn = computed(() => user.value !== null)
/** 后端用 is_admin 卡写接口，前端只拿它决定「设置」入口是否可见 */
const isAdmin = computed(() => user.value?.is_admin === true)

function setError(e: unknown) {
  error.value = e instanceof Error ? e.message : '操作失败，请稍后重试'
}

/** 用账号+密码换取 token 并拉取用户信息，成功后写入 user */
async function login(account: string, password: string): Promise<boolean> {
  loading.value = true
  error.value = null
  try {
    const token = await authApi.login({ account, password })
    authApi.setToken(token.access_token)
    user.value = await authApi.getMe()
    return true
  } catch (e) {
    authApi.clearToken()
    setError(e)
    return false
  } finally {
    loading.value = false
  }
}

/** 注册成功后自动登录，减少一次手动输入 */
async function register(username: string, email: string, password: string): Promise<boolean> {
  loading.value = true
  error.value = null
  try {
    await authApi.register({ username, email, password })
    return await login(username, password)
  } catch (e) {
    setError(e)
    return false
  } finally {
    loading.value = false
  }
}

/** 登出：先吊销服务端 refresh（后端清 HttpOnly Cookie），再清本地 access */
async function logout() {
  await authApi.logoutApi()
  authApi.clearToken()
  user.value = null
  error.value = null
}

/** 应用启动时若本地已有 token，则尝试恢复登录态 */
async function restoreSession(): Promise<void> {
  if (!authApi.getToken()) return
  // 刷新页面后 token 是从 localStorage 读出来的，不会经过 setToken，保活得显式启起来
  authApi.startTokenKeepAlive()
  error.value = null
  try {
    user.value = await authApi.getMe()
  } catch {
    // token 失效：清理并停留在未登录态
    authApi.clearToken()
    user.value = null
  }
}

// 保活续期失败（refresh 也过期或被吊销）：api/auth 已清掉本地 token，这里把用户态一起作废，
// 界面回到未登录（左侧栏显示登录入口），而不是留着一个发不出消息的「假登录」
authApi.onSessionExpired(() => {
  user.value = null
  error.value = '登录已过期，请重新登录'
})

export function useAuth() {
  return {
    user: readonly(user),
    loading: readonly(loading),
    error: readonly(error),
    isLoggedIn,
    isAdmin,
    login,
    register,
    logout,
    restoreSession,
  }
}
