<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useLlm, PLATFORM_PRESET, type LlmProviderConfig } from '../stores/llm'
import { useAuth } from '../stores/auth'
import { useModels } from '../stores/models'
import { getModelProviders, testLlmProvider, type LlmTestResult } from '../api/settings'

/** v-model 控制显隐 */
const open = defineModel<boolean>({ required: true })

const { providers, activeId, addProvider, updateProvider, removeProvider, setActive, saveAll, saving, load, loading: loadingLlm, loadError, saveError: lastSaveError } = useLlm()
const { user, isLoggedIn, logout } = useAuth()
// 保存成功后作废对话框模型列表的缓存，让刚接入的模型立刻可选
const { load: loadModels } = useModels()

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
/** 下方输入表单是否展开：默认收起到列表视图，点行「编辑」或「+ 新增模型」才展开 */
const formOpen = ref(false)
const saved = ref(false)
/** 保存失败原因（带出后端 detail）；空串表示无错误 */
const saveError = ref('')
/** 当前表单对应哪一行；null = 还没有编辑对象（空表时的首次接入） */
const editingId = ref<string | null>(null)
/** 连通性测试状态与结果 */
const testing = ref(false)
const testResult = ref<LlmTestResult | null>(null)

/** 表单草稿：打开时从 store 的当前默认提供商载入 */
const platform = ref<Platform>('deepseek')
const apiKey = ref('')
const baseUrl = ref('')
const defaultModel = ref('')
/** 该行的展示名称（列表与对话下拉里用）；必填 */
const displayName = ref('')
/** 显示名称留空时保存被拦下的标记（打开表单不立刻标红，点了保存才提示） */
const nameError = ref(false)
const supportsThinking = ref(true)

// 任一连接相关字段变化时，清除旧的测试结果避免误导
watch([baseUrl, apiKey, defaultModel], () => {
  testResult.value = null
})

// 重新填上名字就撤掉标红
watch(displayName, (v) => {
  if (v.trim()) nameError.value = false
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
  const target = providers.value.find((p) => p.id === activeId.value) ?? providers.value[0]
  saved.value = false
  saveError.value = ''
  testResult.value = null
  logoutConfirm.value = false
  nameError.value = false
  // 默认只展示列表；一行都没有时直接展开表单引导首次接入
  formOpen.value = !target
  if (target) {
    fillForm(target)
    return
  }
  // 一行都没有：回到默认空表单，保存时新建行
  editingId.value = null
  mode.value = 'provider'
  platform.value = 'deepseek'
  apiKey.value = ''
  displayName.value = ''
  applyPreset('deepseek')
}

/** 把一行配置灌进表单（不改 providers，点保存才写回） */
function fillForm(p: LlmProviderConfig) {
  editingId.value = p.id
  mode.value = p.platform === 'custom' ? 'custom' : 'provider'
  if (p.platform !== 'custom') platform.value = p.platform
  apiKey.value = p.api_key
  baseUrl.value = p.base_url
  defaultModel.value = p.default_model
  displayName.value = p.name
  supportsThinking.value = p.supports_thinking
}

/** 列表行点进来 / 点「编辑」：载入该行并展开表单 */
function editRow(p: LlmProviderConfig) {
  fillForm(p)
  formOpen.value = true
  saved.value = false
  saveError.value = ''
  testResult.value = null
}

/** 新增一行（同平台可重复添加 = 接入多个模型）：先落本地，展开表单，点保存才写库 */
function addRow() {
  addProvider(mode.value === 'custom' ? ('custom' as Platform) : platform.value)
  const p = providers.value[providers.value.length - 1]
  if (p) fillForm(p)
  formOpen.value = true
  saved.value = false
  saveError.value = ''
}

/** 行展示名：优先用已保存的名称，回退平台 label */
function rowLabel(p: LlmProviderConfig): string {
  return p.name || PLATFORM_PRESET[p.platform]?.label || p.platform
}

/** 当前表单落库时实际生效的平台（与 onSave 的 payload.platform 保持一致） */
const formPlatform = computed<Platform>(() => (mode.value === 'custom' ? 'custom' : platform.value))

/** 同平台同模型的重复检测：后端 PUT 对相同 (平台, 模型) 只静默保留第一条，
 * 与其保存后「行凭空蒸发」，不如提前标红拦下（排除正在编辑的本行） */
const dupModel = computed(() => {
  const m = defaultModel.value.trim()
  if (!m) return ''
  const hit = providers.value.some(
    (p) =>
      p.id !== editingId.value &&
      p.platform === formPlatform.value &&
      (p.default_model || '').trim() === m,
  )
  return hit ? m : ''
})

/** 表单当前对应的那一行（给「正在编辑 X」提示；null = 首次接入新建行） */
const editingRow = computed(() => providers.value.find((p) => p.id === editingId.value) ?? null)

/** 整表替换语义下，载失败后的本地列表可能与库里不一致（甚至为空），
 * 继续写回会把其它行清空，所以所有 persist 入口统一拦截 */
async function persist(): Promise<boolean> {
  if (loadError.value) {
    saved.value = false
    saveError.value = '模型配置加载失败，为避免整表覆盖已禁用保存，请点上方「重试」'
    testResult.value = null
    return false
  }
  const ok = await saveAll()
  saved.value = ok
  saveError.value = ok ? '' : lastSaveError.value || '保存失败，请确认已登录且为管理员'
  if (ok) {
    // 只强制重拉，不先 clear：clear 会把列表瞬间置空，若重拉失败（401/500）
    // 对话框的已选模型就被清掉；而成功时重拉本身就会整表替换，无需先清
    void loadModels(true)
  }
  return ok
}

/** 切换默认行（全库只有一个 is_active，决定用户不选模型时用哪个） */
async function makeDefault(p: LlmProviderConfig) {
  setActive(p.id)
  await persist()
}

async function removeOne(p: LlmProviderConfig) {
  if (!window.confirm(`删除「${rowLabel(p)} · ${p.default_model || '未填模型'}」？`)) return
  const wasEditing = editingId.value === p.id
  removeProvider(p.id)
  // 删完就要写库：整表替换下不保存等于下次保存又把它带回来
  if (await persist()) {
    const next = providers.value.find((x) => x.id === activeId.value) ?? providers.value[0]
    if (next) fillForm(next)
    else if (wasEditing) editingId.value = null
  }
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

const hasKey = computed(() => apiKey.value.trim().length > 0)

async function onSave() {
  if (!displayName.value.trim()) {
    nameError.value = true
    saved.value = false
    saveError.value = '显示名称为必填，给这一行模型起个名字（如「Xing4.0 快速」）'
    testResult.value = null
    return
  }
  if (dupModel.value) {
    saved.value = false
    saveError.value = `该平台已有一行使用模型「${dupModel.value}」，重复行会被后端丢弃；请换模型名，或在上方列表点进已有那行编辑`
    testResult.value = null // 否则左下角优先显示旧测试结果，盖掉这条报错
    return
  }
  const payload = {
    platform: mode.value === 'custom' ? ('custom' as Platform) : platform.value,
    // 必填已在前置校验拦住，这里取 trim 后的值落库
    name: displayName.value.trim(),
    base_url: baseUrl.value,
    api_key: apiKey.value,
    default_model: defaultModel.value,
    supports_thinking: supportsThinking.value,
  }
  if (!editingId.value) {
    addProvider(payload.platform)
    editingId.value = providers.value[providers.value.length - 1]?.id ?? null
  }
  if (editingId.value) updateProvider(editingId.value, payload)
  // 整表写回后端数据库；成功后收起表单回到列表视图，失败保持展开供修正
  const ok = await persist()
  if (ok) formOpen.value = false
}

function onCancel() {
  // 收起表单即放弃当前草稿；下次点「编辑」会用库里的值重新灌入
  formOpen.value = false
}

/** 重拉现有配置；成功了顺带把表单回填成新列表里的选中行 */
async function retryLoad() {
  await load()
  if (!loadError.value) loadDraft()
}

/** 账号页退出登录：两步确认，避免误点；离开账号页或关闭弹窗时重置 */
const logoutConfirm = ref(false)

function onLogout() {
  if (!logoutConfirm.value) {
    logoutConfirm.value = true
    return
  }
  logout()
  close()
}

watch(nav, () => {
  logoutConfirm.value = false
})

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
                管理员维护，所有用户共享；一行 = 一个可选模型，同平台可接入多个。
              </p>

              <!-- 载失败横幅：此时本地列表不可信，禁止写回并给重试入口 -->
              <div
                v-if="loadError"
                class="mt-4 flex items-center justify-between gap-3 px-4 py-2.5 rounded-xl border border-red-200 bg-red-50 text-[12.5px] text-red-600"
              >
                <span class="min-w-0 truncate">模型配置加载失败：{{ loadError }}；为避免整表覆盖，保存已禁用</span>
                <button
                  type="button"
                  @click="retryLoad"
                  class="shrink-0 h-7 px-3 rounded-lg border border-red-200 bg-white hover:bg-red-100 transition"
                >
                  {{ loadingLlm ? '重试中…' : '重试' }}
                </button>
              </div>

              <!-- 已接入的模型：一行一个，同平台多行就是多个模型 -->
              <div class="mt-4 rounded-xl border border-stone-200 overflow-hidden">
                <div class="px-4 py-2.5 flex items-center justify-between bg-stone-50 border-b border-stone-200">
                  <span class="text-[11.5px] font-medium tracking-[0.12em] uppercase text-stone-400">已接入的模型</span>
                  <span class="text-[11.5px] text-stone-400">{{ providers.length }} 行</span>
                </div>
                <div
                  v-for="p in providers"
                  :key="p.id"
                  class="flex items-center gap-2 px-4 py-2.5 border-b border-stone-100 last:border-0"
                  :class="p.id === editingId ? 'bg-white' : ''"
                >
                  <button type="button" class="min-w-0 flex-1 text-left" @click="editRow(p)">
                    <span class="block text-[13px] text-stone-800 truncate">{{ rowLabel(p) }}</span>
                    <span class="block text-[11.5px] text-stone-400 truncate">
                      {{ p.default_model || '未填模型名（该行不会出现在对话模型列表）' }}
                    </span>
                  </button>
                  <span
                    v-if="p.id === activeId"
                    class="shrink-0 rounded-full bg-[#EAF0E4] px-2 py-0.5 text-[11px] text-[#4d7d4f]"
                    >默认</span
                  >
                  <span
                    v-if="p.supports_thinking"
                    class="shrink-0 rounded-full border border-stone-200 px-2 py-0.5 text-[11px] text-stone-500"
                    >深度</span
                  >
                  <button
                    type="button"
                    @click="editRow(p)"
                    class="shrink-0 h-7 px-2.5 rounded-lg text-[12px] text-stone-500 hover:bg-stone-100 transition"
                    title="编辑这一行的配置"
                  >
                    编辑
                  </button>
                  <button
                    v-if="p.id !== activeId"
                    type="button"
                    @click="makeDefault(p)"
                    class="shrink-0 h-7 px-2.5 rounded-lg text-[12px] text-stone-500 hover:bg-stone-100 transition"
                    title="设为默认：用户不选模型时用它"
                  >
                    设为默认
                  </button>
                  <button
                    type="button"
                    @click="removeOne(p)"
                    class="shrink-0 h-7 w-7 grid place-items-center rounded-lg text-stone-400 hover:text-red-500 hover:bg-stone-100 transition"
                    title="删除这一行"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                    </svg>
                  </button>
                </div>
                <p v-if="!providers.length" class="px-4 py-3 text-[12px] text-stone-400">
                  还没有接入模型；点下方「+ 新增模型」开始配置。
                </p>
                <button
                  type="button"
                  @click="addRow"
                  class="w-full px-4 py-2.5 text-left text-[12.5px] text-stone-600 hover:bg-stone-50 transition"
                >
                  + 新增模型（同平台可重复添加）
                </button>
              </div>

              <!-- 配置表单容器：默认收起，点行「编辑」或「+ 新增模型」才展开 -->
              <div v-if="formOpen" class="mt-4 rounded-xl bg-stone-50 border border-stone-200 p-4">
                <!-- 表单落在哪一行：保存会整表写回，这里明确告知正在改谁 -->
                <div class="mb-3 flex items-baseline justify-between gap-2 text-[12px]">
                  <span class="min-w-0 truncate text-stone-500">
                    <template v-if="editingRow">
                      正在编辑：<b class="font-medium text-stone-700">{{ rowLabel(editingRow) }}</b>
                      · {{ editingRow.default_model || '未填模型名' }}
                    </template>
                    <template v-else>首次接入：保存后将新建一行</template>
                  </span>
                  <span class="shrink-0 text-stone-400">保存后自动收起，取消不写库</span>
                </div>

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
                      title="密钥存在服务端并全局生效（仅管理员可读写），所有用户的对话共用这份配置。"
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

                <!-- 显示名称：同一平台接多个模型时用来区分（如「快速档」「深度档」）；必填 -->
                <label class="mt-3 block">
                  <span class="block text-[12.5px] font-medium text-stone-600 mb-1.5">
                    显示名称
                    <span class="ml-0.5 text-red-500">*</span>
                    <span class="ml-1 text-[11px] font-normal text-stone-400">（必填，列表与对话下拉里展示）</span>
                  </span>
                  <input
                    v-model="displayName"
                    type="text"
                    placeholder="如：Xing4.0 快速"
                    class="w-full h-9 rounded-lg border bg-white px-2.5 text-[13px] text-stone-800 outline-none transition"
                    :class="nameError ? 'border-red-400 focus:border-red-500' : 'border-stone-200 focus:border-stone-400'"
                  />
                  <p v-if="nameError" class="mt-1 text-[11.5px] text-red-500">
                    显示名称不能为空，否则无法保存
                  </p>
                </label>

                <!-- 模型名称（可选）：已从自定义设置中提取，常驻表单 -->
                <label class="mt-3 block">
                  <span class="block text-[12.5px] font-medium text-stone-600 mb-1.5">
                    模型名称
                    <span class="ml-1 text-[11px] font-normal text-stone-400">（一行一个模型）</span>
                  </span>
                  <input
                    v-model="defaultModel"
                    type="text"
                    placeholder="留空则该行不会出现在对话模型列表"
                    class="w-full h-9 rounded-lg border bg-white px-2.5 text-[13px] text-stone-800 outline-none transition"
                    :class="dupModel ? 'border-red-400 focus:border-red-500' : 'border-stone-200 focus:border-stone-400'"
                  />
                  <p v-if="dupModel" class="mt-1 text-[11.5px] text-red-500">
                    该平台已有一行使用模型「{{ dupModel }}」：保存后重复行会被后端丢弃，请换个模型名或直接编辑已有那行
                  </p>
                </label>

                <!-- 选择模式开关：原藏在折叠区的「支持深度思考」显性化，
                     决定对话页该模型是否展示 快速/深度 档位选择 -->
                <div class="mt-4 flex items-center justify-between gap-3">
                  <span class="text-[12.5px] font-medium text-stone-600">
                    选择模式
                    <span class="block text-[11px] font-normal text-stone-400">开启后对话页可切换 快速/深度 档（需模型本身支持深度思考）</span>
                  </span>
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="supportsThinking"
                    @click="supportsThinking = !supportsThinking; saved = false"
                    class="relative h-[22px] w-[40px] shrink-0 rounded-full transition"
                    :class="supportsThinking ? 'bg-[#86A964]' : 'bg-stone-300'"
                  >
                    <span
                      class="absolute top-[2px] left-[2px] h-[18px] w-[18px] rounded-full bg-white shadow transition-transform"
                      :class="supportsThinking ? 'translate-x-[18px]' : ''"
                    />
                  </button>
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
                    <span v-else-if="saveError" class="text-red-500">{{ saveError }}</span>
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
                      :disabled="saving || !!loadError"
                      @click="onSave"
                      class="h-8 px-4 rounded-lg bg-stone-900 text-[13px] font-medium text-white hover:bg-black transition disabled:opacity-60 disabled:cursor-not-allowed"
                      :title="loadError ? '模型配置加载失败，请先重试加载再保存' : ''"
                    >
                      {{ saving ? '保存中…' : '保存' }}
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 账号与余额 -->
            <template v-else-if="nav === 'account'">
              <h3 class="text-[17px] font-semibold text-stone-800">账号与余额</h3>
              <p class="mt-1 text-[12.5px] text-stone-400">
                查看当前登录账号，余额与用量统计即将开放。
              </p>

              <div v-if="isLoggedIn" class="mt-4 flex items-center gap-3 px-4 py-3.5 rounded-xl border border-stone-200">
                <span class="h-10 w-10 shrink-0 rounded-full bg-gradient-to-br from-stone-300 to-stone-500 grid place-items-center text-[14px] font-semibold text-white">
                  {{ (user?.username || '?').charAt(0).toUpperCase() }}
                </span>
                <span class="min-w-0 flex-1 leading-tight">
                  <span class="block text-[13.5px] font-semibold text-stone-800 truncate">{{ user?.username }}</span>
                  <span class="block text-[11.5px] text-stone-500 truncate">{{ user?.email }}</span>
                </span>
                <button
                  type="button"
                  @click="onLogout"
                  class="h-8 px-4 shrink-0 rounded-lg border text-[13px] transition"
                  :class="
                    logoutConfirm
                      ? 'border-red-200 bg-red-50 text-red-600 hover:bg-red-100'
                      : 'border-stone-200 text-stone-600 hover:border-red-200 hover:text-red-600'
                  "
                >
                  {{ logoutConfirm ? '确认退出' : '退出登录' }}
                </button>
              </div>
              <p v-else class="mt-4 text-[12.5px] text-stone-400">当前未登录，依赖账户的功能不可用。</p>
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
