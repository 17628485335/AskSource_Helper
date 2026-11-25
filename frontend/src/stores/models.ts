/**
 * 对话可选模型存储（组合式单例）
 *
 * 与 stores/llm.ts 的分工：那份是管理员编辑的全量配置（含密钥，仅管理员能读写），
 * 这份只读 /settings/models（登录即可，字段里没有密钥），给对话框的模型下拉用。
 * 列表进程内缓存一次，登录切换或管理员改动后调 load(true) 强制刷新。
 */

import { computed, readonly, ref } from 'vue'
import { getChatModels, type ChatModelOption } from '../api/settings'

const models = ref<ChatModelOption[]>([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')

/** 真正能对话的那些行：available=false 是管理员接了但构建失败（密钥失效等）。
 * 字段缺省按可用处理，免得前端比后端新就把所有模型藏掉。 */
const usableModels = computed(() => models.value.filter((m) => m.available !== false))

/** 管理员标记为生效的那条；生效行本身构建失败时退到第一个能用的 */
const defaultModel = computed(
  () => usableModels.value.find((m) => m.is_active) ?? usableModels.value[0] ?? null,
)

async function load(force = false): Promise<void> {
  if (loading.value || (loaded.value && !force)) return
  loading.value = true
  error.value = ''
  try {
    models.value = await getChatModels()
    loaded.value = true
  } catch (e) {
    // 未登录 / 后端未启动时静默降级：下拉只剩「默认」，对话仍按后端生效配置走
    error.value = e instanceof Error ? e.message : '获取模型列表失败'
  } finally {
    loading.value = false
  }
}

/** 退出登录或管理员保存新配置后作废缓存 */
function clear(): void {
  models.value = []
  loaded.value = false
  error.value = ''
}

export function useModels() {
  return {
    models: readonly(models),
    usableModels,
    loading: readonly(loading),
    loaded: readonly(loaded),
    error: readonly(error),
    defaultModel,
    load,
    clear,
  }
}
