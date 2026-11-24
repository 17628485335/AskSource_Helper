<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useLlm, PLATFORM_PRESET, type LlmProviderConfig } from '../stores/llm'
import { getModelProviders, testLlmProvider, type LlmTestResult } from '../api/settings'

/** v-model 控制显隐 */
const open = defineModel<boolean>({ required: true })

const { providers, activeId, addProvider, updateProvider, saveAll, saving } = useLlm()

type NavKey = 'account' | 'general' | 'model' | 'plugins' | 'agent'
type Platform = LlmProviderConfig['platform']

const NAV_ITEMS: { key: NavKey; label: string }[] = [
  { key: 'account', label: '账号与余额' },
  { key: 'general', label: '通用设置' },
  { key: 'model', label: '模型' },
  { key: 'plugins', label: '内置插件' },
  { key: 'agent', label: 'Agent 预设' },
]

const nav = ref<NavKey>('model')
/** 表单容器顶部分段切换：第三方提供商 / 自定义 API */
const mode = ref<'provider' | 'custom'>('provider')
/** “自定义设置”折叠行是否展开 */
const customOpen = ref(false)
const saved = ref(false)
const saveError = ref(false)
/** 连通性测试状态与结果 */
const testing = ref(false)
const testResult = ref<LlmTestResult | null>(null)

/** 表单草稿：打开时从 store 的当前默认提供商载入 */
const platform = ref<Platform>('deepseek')
const apiKey = ref('')
const baseUrl = ref('')
const defaultModel = ref('')
const supportsThinking = ref(true)

// 任一连接相关字段变化时，清除旧的测试结果避免误导
watch([baseUrl, apiKey, defaultModel], () => {
  testResult.value = null
})

/** 模型提供商下拉选项：从后端 /settings/model-providers 动态获取（含预填用 base_url） */
const providerOptions = ref<{ value: Platform; label: string; base_url: string }[]>([])
const loadingProviders = ref(false)
const providersError = ref<string | null>(null)

/** 拉取失败时的兜底：回退到本地预置的第三方平台（base_url 已改由后端提供，兜底留空） */
function fallbackOptions(): { value: Platform; label: string; base_url: string }[] {
  return (Object.keys(PLATFORM_PRESET) as Platform[])
    .filter((p) => p !== 'custom')
    .map((p) => ({ value: p, label: PLATFORM_PRESET[p].label, base_url: '' }))
}

async function loadProviders() {
  loadingProviders.value = true
  providersError.value = null
  try {
    const list = await getModelProviders()
    providerOptions.value = list.length
      ? list.map((o) => ({ value: o.value as Platform, label: o.label, base_url: o.base_url }))
      : fallbackOptions()
  } catch {
    providersError.value = '提供商选项加载失败，已回退本地默认'
    providerOptions.value = fallbackOptions()
  } finally {
    loadingProviders.value = false
  }
  // 初次打开时选项晚于 applyPreset 到位：若仍为 provider 模式且端点为空，按当前平台补填
  if (mode.value === 'provider' && !baseUrl.value && providerOptions.value.length) {
    applyPreset(platform.value)
  }
}

function applyPreset(p: Platform) {
  const preset = PLATFORM_PRESET[p]
  // base_url 取后端返回的地址；无匹配则留空由用户自行填写
  const opt = providerOptions.value.find((o) => o.value === p)
  baseUrl.value = opt?.base_url ?? ''
  if (!preset) return
  defaultModel.value = preset.default_model
  supportsThinking.value = preset.supports_thinking
}

function loadDraft() {
  const active = providers.value.find((p) => p.id === activeId.value)
  if (active) {
    mode.value = active.platform === 'custom' ? 'custom' : 'provider'
    if (active.platform !== 'custom') platform.value = active.platform
    apiKey.value = active.api_key
    baseUrl.value = active.base_url
    defaultModel.value = active.default_model
    supportsThinking.value = active.supports_thinking
  } else {
    mode.value = 'provider'
    platform.value = 'deepseek'
    apiKey.value = ''
    applyPreset('deepseek')
  }
  customOpen.value = false
  saved.value = false
  saveError.value = false
  testResult.value = null
}

watch(open, (v) => {
  if (v) {
    loadDraft()
    if (providerOptions.value.length === 0) loadProviders()
  }
})

function onPlatformChange() {
  applyPreset(platform.value)
  saved.value = false
}

function close() {
  open.value = false
}

/** 当前生效的提供商展示名（优先用后端返回的 label，与下拉联动） */
const providerLabel = computed(() => {
  if (mode.value === 'custom') return '自定义模型 API'
  const opt = providerOptions.value.find((o) => o.value === platform.value)
  return opt?.label ?? PLATFORM_PRESET[platform.value]?.label ?? platform.value
})
const hasKey = computed(() => apiKey.value.trim().length > 0)

/** “编辑”按钮：展开自定义设置折叠区便于修改 */
function onEdit() {
  customOpen.value = true
}

async function onSave() {
  const payload = {
    platform: mode.value === 'custom' ? ('custom' as Platform) : platform.value,
    name: providerLabel.value,
    base_url: baseUrl.value,
    api_key: apiKey.value,
    default_model: defaultModel.value,
    supports_thinking: supportsThinking.value,
  }
  if (activeId.value) {
    updateProvider(activeId.value, payload)
  } else {
    addProvider(payload.platform)
    if (activeId.value) updateProvider(activeId.value, payload)
  }
  // 整表写回后端数据库；成功后才标记已保存
  const ok = await saveAll()
  saved.value = ok
  saveError.value = !ok
}

function onCancel() {
  loadDraft()
}

/** 用当前表单草稿值探测连通性 / 密钥有效性（无需先保存） */
async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testLlmProvider({
      base_url: baseUrl.value,
      api_key: apiKey.value,
      default_model: defaultModel.value,
    })
  } catch (e) {
    testResult.value = {
      ok: false,
      detail: e instanceof Error ? e.message : '测试请求失败，请确认已登录且后端可用',
      model_count: null,
    }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      @mousedown.self="close"
    >
      <div
        class="w-[min(94vw,800px)] h-[85vh] flex flex-col rounded-2xl bg-white shadow-xl shadow-stone-900/10 overflow-hidden"
        @mousedown.stop
      >
        <!-- 顶部栏 -->
        <div class="flex items-center justify-between px-6 h-14 shrink-0 border-b border-stone-200">
          <h2 class="text-[16px] font-semibold text-stone-800">设置</h2>
          <div class="flex items-center gap-2">
            <button
              type="button"
              @click="close"
              class="h-8 w-8 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 transition"
              title="关闭"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>
        </div>

        <!-- 主体：左右双栏 -->
        <div class="flex flex-1 min-h-0">
          <!-- 左侧导航 -->
          <nav class="w-[180px] shrink-0 border-r border-stone-200 py-4 px-3 space-y-1">
            <button
              v-for="item in NAV_ITEMS"
              :key="item.key"
              type="button"
              @click="nav = item.key"
              class="w-full h-9 flex items-center gap-2.5 rounded-lg px-3 text-[13px] transition"
              :class="nav === item.key ? 'bg-stone-100 text-stone-900 font-medium' : 'text-stone-600 hover:bg-stone-100'"
            >
              <!-- 账号与余额 -->
              <svg v-if="item.key === 'account'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="8" r="4" />
                <path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
              </svg>
              <!-- 通用设置 -->
              <svg v-else-if="item.key === 'general'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                <path d="M4 8h10M18 8h2M4 16h4M12 16h8" />
                <circle cx="16" cy="8" r="2" />
                <circle cx="10" cy="16" r="2" />
              </svg>
              <!-- 模型 -->
              <svg v-else-if="item.key === 'model'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="6" y="6" width="12" height="12" rx="2" />
                <path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5" />
              </svg>
              <!-- 内置插件 -->
              <svg v-else-if="item.key === 'plugins'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10 3v3a2 2 0 0 1-2 2H5a2 2 0 0 0-2 2v2h3a2 2 0 0 1 2 2v2h3a2 2 0 0 0 2-2h3v-3a2 2 0 0 1 2-2h3v-2a2 2 0 0 0-2-2h-3a2 2 0 0 1-2-2V3h-3" transform="rotate(45 12 12)" />
              </svg>
              <!-- Agent 预设 -->
              <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="8" width="16" height="12" rx="2" />
                <path d="M12 8V4M8 14h.01M16 14h.01M9 18h6" />
                <circle cx="12" cy="3" r="1" />
              </svg>
              {{ item.label }}
            </button>
          </nav>

          <!-- 右侧内容区 -->
          <div class="flex-1 min-w-0 overflow-y-auto scroll-thin px-7 py-6">
            <!-- 模型 -->
            <template v-if="nav === 'model'">
              <h3 class="text-[17px] font-semibold text-stone-800">模型</h3>
              <p class="mt-1 text-[12.5px] text-stone-400">
                管理模型提供商接入与密钥，切换后新对话立即生效。
              </p>

              <!-- 状态条卡片：当前提供商 -->
              <div class="mt-4 flex items-center justify-between px-4 py-3 rounded-xl border border-stone-200">
                <span class="flex items-center gap-2 text-[13.5px] font-medium text-stone-800">
                  {{ providerLabel }}
                  <span class="h-2 w-2 rounded-full" :class="hasKey ? 'bg-[#86A964]' : 'bg-[#C0857B]'" :title="hasKey ? '密钥已配置' : '密钥未配置'" />
                </span>
                <button
                  type="button"
                  @click="onEdit"
                  class="h-7 px-3 rounded-lg border border-stone-200 text-[12px] text-stone-600 hover:bg-stone-100 transition"
                >
                  编辑
                </button>
              </div>

              <!-- 配置表单容器 -->
              <div class="mt-4 rounded-xl bg-stone-50 border border-stone-200 p-4">
                <!-- 分段切换 Tab -->
                <div class="flex rounded-lg bg-stone-200/70 p-1 text-[12.5px] font-medium">
                  <button
                    type="button"
                    @click="mode = 'provider'; saved = false"
                    class="flex-1 h-8 rounded-md transition"
                    :class="mode === 'provider' ? 'bg-white text-stone-800 shadow-sm' : 'text-stone-500 hover:text-stone-600'"
                  >
                    第三方模型提供商
                  </button>
                  <button
                    type="button"
                    @click="mode = 'custom'; saved = false"
                    class="flex-1 h-8 rounded-md transition"
                    :class="mode === 'custom' ? 'bg-white text-stone-800 shadow-sm' : 'text-stone-500 hover:text-stone-600'"
                  >
                    自定义模型 API
                  </button>
                </div>

                <p class="mt-3 text-[12px] text-stone-400">
                  {{ mode === 'provider'
                    ? '选择平台后将自动填充兼容 Endpoint，只需填写 API 密钥。'
                    : '接入任意 OpenAI 兼容服务，需填写 API 端点与密钥。' }}
                </p>

                <!-- 提供商 / 端点 -->
                <label v-if="mode === 'provider'" class="mt-3 block">
                  <span class="block text-[12.5px] font-medium text-stone-600 mb-1.5">提供商</span>
                  <select
                    v-model="platform"
                    @change="onPlatformChange"
                    :disabled="loadingProviders"
                    class="w-full h-9 rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] text-stone-800 outline-none focus:border-stone-400 transition disabled:opacity-60"
                  >
                    <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                  <p v-if="loadingProviders" class="mt-1 text-[11.5px] text-stone-400">加载提供商选项中…</p>
                  <p v-else-if="providersError" class="mt-1 text-[11.5px] text-amber-600">{{ providersError }}</p>
                </label>
                <label v-else class="mt-3 block">
                  <span class="block text-[12.5px] font-medium text-stone-600 mb-1.5">API 端点</span>
                  <input
                    v-model="baseUrl"
                    type="text"
                    placeholder="https://your-endpoint/v1"
                    class="w-full h-9 rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] text-stone-800 outline-none focus:border-stone-400 transition"
                  />
                </label>

                <!-- API 密钥 -->
                <div class="mt-3">
                  <span class="flex items-center gap-1.5 text-[12.5px] font-medium text-stone-600 mb-1.5">
                    API 密钥
                    <span
                      class="h-4 w-4 grid place-items-center rounded-full border border-stone-300 text-[10px] text-stone-400 cursor-help"
                      title="保存后随配置持久化到你登录账户的数据库（需登录），跨设备同步。"
                    >?</span>
                  </span>
                  <input
                    v-model="apiKey"
                    type="password"
                    placeholder="sk-..."
                    autocomplete="off"
                    class="w-full h-9 rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] text-stone-800 outline-none focus:border-stone-400 transition"
                  />
                </div>

                <!-- 模型名称（可选）：已从自定义设置中提取，常驻表单 -->
                <label class="mt-3 block">
                  <span class="block text-[12.5px] font-medium text-stone-600 mb-1.5">
                    模型名称
                    <span class="ml-1 text-[11px] font-normal text-stone-400">（可选）</span>
                  </span>
                  <input
                    v-model="defaultModel"
                    type="text"
                    placeholder="留空则使用提供商默认模型"
                    class="w-full h-9 rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] text-stone-800 outline-none focus:border-stone-400 transition"
                  />
                </label>

                <!-- 可折叠的自定义设置 -->
                <div class="mt-4">
                  <button
                    type="button"
                    @click="customOpen = !customOpen"
                    class="flex items-center gap-1.5 text-[12.5px] font-medium text-stone-600 hover:text-stone-800 transition"
                  >
                    <svg
                      width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
                      class="transition-transform"
                      :class="customOpen ? 'rotate-90' : ''"
                    >
                      <path d="M9 6l6 6-6 6" />
                    </svg>
                    自定义设置
                  </button>
                  <div v-if="customOpen" class="mt-3">
                    <label class="flex items-center gap-2">
                      <input v-model="supportsThinking" type="checkbox" class="h-4 w-4 rounded accent-stone-700" />
                      <span class="text-[12.5px] text-stone-600">支持深度思考</span>
                    </label>
                  </div>
                </div>

                <!-- 底部操作区 -->
                <div class="mt-4 pt-3 border-t border-stone-200 flex items-center justify-between gap-2">
                  <!-- 左侧：连通性测试 / 保存结果反馈 -->
                  <div class="min-w-0 text-[12px] truncate">
                    <span v-if="testing" class="text-stone-400">测试连接中…</span>
                    <span v-else-if="testResult?.ok" class="text-[#4d7d4f]">
                      ✓ {{ testResult.detail }}<template v-if="testResult.model_count != null">（可用模型 {{ testResult.model_count }} 个）</template>
                    </span>
                    <span v-else-if="testResult" class="text-red-500">✕ {{ testResult.detail }}</span>
                    <span v-else-if="saveError" class="text-red-500">保存失败，请确认已登录</span>
                    <span v-else-if="saved" class="text-[#4d7d4f]">已保存 ✓</span>
                  </div>
                  <!-- 右侧：操作按钮 -->
                  <div class="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      :disabled="testing || !hasKey"
                      @click="onTest"
                      class="h-8 px-3 rounded-lg border border-stone-200 text-[13px] text-stone-600 hover:bg-stone-100 transition disabled:opacity-60 disabled:cursor-not-allowed"
                      :title="!hasKey ? '请先填写 API 密钥' : '探测端点连通性与密钥有效性'"
                    >
                      {{ testing ? '测试中…' : '测试连接' }}
                    </button>
                    <button
                      type="button"
                      @click="onCancel"
                      class="h-8 px-4 rounded-lg text-[13px] text-stone-600 hover:bg-stone-100 transition"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      :disabled="saving"
                      @click="onSave"
                      class="h-8 px-4 rounded-lg bg-stone-900 text-[13px] font-medium text-white hover:bg-black transition disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      {{ saving ? '保存中…' : '保存' }}
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 其他导航：占位 -->
            <template v-else>
              <h3 class="text-[17px] font-semibold text-stone-800">
                {{ NAV_ITEMS.find((i) => i.key === nav)?.label }}
              </h3>
              <p class="mt-1 text-[12.5px] text-stone-400">该模块尚在建设中，敬请期待。</p>
            </template>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
