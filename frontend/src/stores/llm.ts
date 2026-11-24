/**
 * LLM 配置存储（组合式单例）
 *
 * 管理各平台（DeepSeek / 硅基流动 / 阿里百炼 / 自定义）的接入配置。
 * 通过 /settings/llm 接口持久化到后端数据库（需登录），不再使用 localStorage。
 */

import { readonly, ref } from 'vue'
import {
  getLlmProviders,
  putLlmProviders,
  type LlmProviderDto,
} from '../api/settings'

export interface LlmProviderConfig {
  id: string
  platform: 'deepseek' | 'siliconflow' | 'bailian' | 'custom'
  name: string
  base_url: string
  api_key: string
  default_model: string
  supports_thinking: boolean
}

/** 选择平台时预置的名称与默认模型（base_url 已改由后端 /settings/model-providers 提供） */
export const PLATFORM_PRESET: Record<
  LlmProviderConfig['platform'],
  { label: string; default_model: string; supports_thinking: boolean }
> = {
  deepseek: {
    label: 'DeepSeek',
    default_model: 'deepseek-chat',
    supports_thinking: true,
  },
  siliconflow: {
    label: '硅基流动',
    default_model: 'Qwen/Qwen3-32B',
    supports_thinking: true,
  },
  bailian: {
    label: '阿里百炼',
    default_model: 'qwen-plus',
    supports_thinking: true,
  },
  custom: {
    label: '自定义',
    default_model: '',
    supports_thinking: false,
  },
}

const providers = ref<LlmProviderConfig[]>([])
const activeId = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

/** 后端 DTO → 本地配置（id 统一为字符串） */
function fromDto(dto: LlmProviderDto): LlmProviderConfig {
  return {
    id: dto.id != null ? String(dto.id) : uid(),
    platform: (dto.platform as LlmProviderConfig['platform']) || 'custom',
    name: dto.name,
    base_url: dto.base_url,
    api_key: dto.api_key,
    default_model: dto.default_model,
    supports_thinking: dto.supports_thinking,
  }
}

/** 本地配置 → 后端 DTO（依 activeId 标记 is_active） */
function toDto(p: LlmProviderConfig): LlmProviderDto {
  return {
    platform: p.platform,
    name: p.name,
    base_url: p.base_url,
    api_key: p.api_key,
    default_model: p.default_model,
    supports_thinking: p.supports_thinking,
    is_active: p.id === activeId.value,
  }
}

/** 从后端 /settings/llm 载入当前登录用户的配置（需登录） */
async function load(): Promise<void> {
  loading.value = true
  try {
    const list = await getLlmProviders()
    providers.value = list.map(fromDto)
    activeId.value =
      providers.value.find((p) => list.find((d) => String(d.id) === p.id)?.is_active)?.id ??
      providers.value[0]?.id ??
      null
  } catch {
    // 未登录或后端不可用时保持空态，不阻断界面
  } finally {
    loading.value = false
  }
}

/** 将当前配置整表写回后端数据库（需登录） */
async function saveAll(): Promise<boolean> {
  saving.value = true
  try {
    const list = await putLlmProviders(providers.value.map(toDto))
    // 用后端返回的真实 id 回填本地，保证后续更新一致
    providers.value = list.map(fromDto)
    activeId.value = list.find((d) => d.is_active)?.id != null
      ? String(list.find((d) => d.is_active)!.id)
      : providers.value[0]?.id ?? null
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

function createProvider(platform: LlmProviderConfig['platform'] = 'deepseek'): LlmProviderConfig {
  const preset = PLATFORM_PRESET[platform]
  return {
    id: uid(),
    platform,
    name: preset.label,
    base_url: '',
    api_key: '',
    default_model: preset.default_model,
    supports_thinking: preset.supports_thinking,
  }
}

/** 以下变更仅改本地状态，落库需显式调用 saveAll() */
function addProvider(platform: LlmProviderConfig['platform'] = 'deepseek'): void {
  const p = createProvider(platform)
  providers.value.push(p)
  if (!activeId.value) activeId.value = p.id
}

function updateProvider(id: string, patch: Partial<LlmProviderConfig>): void {
  const idx = providers.value.findIndex((p) => p.id === id)
  if (idx === -1) return
  providers.value[idx] = { ...providers.value[idx], ...patch }
}

function removeProvider(id: string): void {
  providers.value = providers.value.filter((p) => p.id !== id)
  if (activeId.value === id) activeId.value = providers.value[0]?.id ?? null
}

/** 切换平台时同步刷新该行的预置值（base_url 由调用方按后端选项回填） */
function switchPlatform(id: string, platform: LlmProviderConfig['platform']): void {
  const preset = PLATFORM_PRESET[platform]
  updateProvider(id, {
    platform,
    default_model: preset.default_model,
    supports_thinking: preset.supports_thinking,
  })
}

function setActive(id: string): void {
  activeId.value = id
}

export function useLlm() {
  return {
    providers: readonly(providers),
    activeId: readonly(activeId),
    loading: readonly(loading),
    saving: readonly(saving),
    load,
    saveAll,
    addProvider,
    updateProvider,
    removeProvider,
    switchPlatform,
    setActive,
  }
}
