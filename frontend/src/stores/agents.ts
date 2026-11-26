/**
 * 对话可选 agent 存储（组合式单例）
 *
 * 只读 /agents 的启用列表；管理员在设置里改完 agent 后调 load(true) 强制刷新。
 * 选中的 agent_key 存 localStorage，刷新页面后保持当前选择。
 */

import { computed, readonly, ref, watch } from 'vue'
import { listAgents, type AgentDto } from '../api/settings'

const STORAGE_KEY = 'asksource_agent_key'

const agents = ref<AgentDto[]>([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const activeKey = ref<string | null>(localStorage.getItem(STORAGE_KEY))

const activeAgent = computed(() => agents.value.find((a) => a.agent_key === activeKey.value) ?? null)

watch(activeKey, (key) => {
  if (key) localStorage.setItem(STORAGE_KEY, key)
  else localStorage.removeItem(STORAGE_KEY)
})

watch(agents, (list) => {
  if (!list.length) return
  if (list.some((a) => a.agent_key === activeKey.value)) return
  // 选中的 agent 被停用/删除时回落到 chat，再退到第一条
  activeKey.value = (list.find((a) => a.agent_key === 'chat') ?? list[0]).agent_key
})

async function load(force = false): Promise<void> {
  if (loading.value || (loaded.value && !force)) return
  loading.value = true
  error.value = ''
  try {
    agents.value = await listAgents(false)
    loaded.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : '获取 agent 列表失败'
  } finally {
    loading.value = false
  }
}

function setActive(key: string | null): void {
  activeKey.value = key
}

/** 退出登录时作废缓存，保留 key 方便下次同一账号继续使用 */
function clear(): void {
  agents.value = []
  loaded.value = false
  error.value = ''
}

export function useAgents() {
  return {
    agents: readonly(agents),
    activeAgent,
    activeKey,
    loading: readonly(loading),
    loaded: readonly(loaded),
    error: readonly(error),
    load,
    setActive,
    clear,
  }
}
