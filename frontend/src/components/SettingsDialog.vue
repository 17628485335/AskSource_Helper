<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  useLlm,
  PLATFORM_PRESET,
  CONTEXT_SIZES,
  DEFAULT_CONTEXT_SIZE,
  normalizeContextSize,
  type LlmProviderConfig,
} from '../stores/llm'
import { useAuth } from '../stores/auth'
import * as authApi from '../api/auth'
import { useTheme, type ThemeMode } from '../stores/theme'
import { useModels } from '../stores/models'
import {
  activateAgentPrompt,
  composeSystemPrompt,
  createAgent,
  createAgentBinding,
  createAgentDoc,
  createAgentMemory,
  createAgentPrompt,
  deleteAgent,
  deleteAgentMemory,
  generateContextContent,
  getModelProviders,
  listAgentBindings,
  listAgentDocs,
  listAgentMemories,
  listAgentPrompts,
  listAgents,
  listTools,
  testLlmProvider,
  updateAgent,
  updateAgentBinding,
  updateAgentDoc,
  updateAgentMemory,
  type AgentContextDocDto,
  type AgentMemoryDto,
  type AgentDto,
  type AgentPromptDto,
  type ContextGenerateKind,
  type ContextResolver,
  type ContextTrustLevel,
  type LlmTestResult,
  type ToolDto,
} from '../api/settings'
import { useAgents } from '../stores/agents'

/** v-model 控制显隐 */
const open = defineModel<boolean>({ required: true })

const { providers, activeId, addProvider, updateProvider, removeProvider, setActive, saveAll, saving, load, loading: loadingLlm, loadError, saveError: lastSaveError } = useLlm()
const { user, isLoggedIn, isAdmin, logout, setUser } = useAuth()
const { mode: themeMode, setMode: setThemeMode } = useTheme()
const themeOptions: { value: ThemeMode; label: string }[] = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]
// 保存成功后作废对话框模型列表的缓存，让刚接入的模型立刻可选
const { load: loadModels } = useModels()
// 保存 agent 配置后立刻刷新对话区可选列表
const { load: loadChatAgents } = useAgents()

type NavKey = 'account' | 'general' | 'model' | 'plugins' | 'agent'
type Platform = LlmProviderConfig['platform']

const NAV_ITEMS: { key: NavKey; label: string }[] = [
  { key: 'account', label: '账户' },
  { key: 'general', label: '通用设置' },
  { key: 'model', label: '模型' },
  { key: 'plugins', label: '内置插件' },
  { key: 'agent', label: 'Agent 预设' },
]

/** Agent 管理只有管理员可见；普通用户看不到占位入口 */
const visibleNavItems = computed(() =>
  NAV_ITEMS.filter((item) => item.key !== 'agent' || isAdmin.value),
)

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
const contextSize = ref(DEFAULT_CONTEXT_SIZE)

/* ---------------- Agent 管理 ---------------- */
const adminAgents = ref<AgentDto[]>([])
const adminPrompts = ref<AgentPromptDto[]>([])
const agentTools = ref<ToolDto[]>([])
const agentLoading = ref(false)
const agentError = ref('')
const agentSaved = ref('')
const saveToast = ref('')
let saveToastTimer: number | undefined

function showSaveToast(message: string) {
  saveToast.value = message
  if (saveToastTimer) window.clearTimeout(saveToastTimer)
  saveToastTimer = window.setTimeout(() => {
    saveToast.value = ''
  }, 3000)
}

onUnmounted(() => {
  if (saveToastTimer) window.clearTimeout(saveToastTimer)
})
const agentFormOpen = ref(false)
const agentEditingId = ref<number | null>(null)
const agKey = ref('')
const agName = ref('')
const agDescription = ref('')
const agToolMode = ref<'all' | 'picked'>('all')
const agToolNames = ref<string[]>([])
const agPrompt = ref('')
const agPromptNote = ref('')
const systemPromptGenerating = ref(false)
const systemPromptSaving = ref(false)
const systemPromptError = ref('')

interface ContextDraft {
  localId: number
  bindingId: number | null
  docId: number | null
  key: string
  title: string
  resolver: ContextResolver
  refKey: string
  content: string
  enabled: boolean
  priority: number
  maxTokens: number
  trustLevel: ContextTrustLevel
  trustHint: string
  globalDoc: boolean
}

interface ContextPreset {
  key: string
  title: string
  description: string
  resolver: ContextResolver
  refKey: string
  priority: number
  maxTokens: number
  trustLevel: ContextTrustLevel
  trustHint: string
  enabled: boolean
}

const CONTEXT_PRESETS: Record<'agent' | 'user' | 'memory', ContextPreset[]> = {
  agent: [
    {
      key: 'identity',
      title: 'Identity',
      description: '定义 Agent 是谁、能做什么、不能做什么，例如名称、角色定位和服务边界。用户问「你是谁」时以此为准；按 anchor 级注入，作为事实锚点，不作为规则执行。',
      resolver: 'agent_doc',
      refKey: 'identity',
      priority: 10,
      maxTokens: 800,
      trustLevel: 'anchor',
      trustHint: '事实锚点',
      enabled: true,
    },
    {
      key: 'soul',
      title: 'Soul',
      description: '定义这个 Agent 的性格、语气与行为底线，例如「先给结论，再展开解释」「不使用感叹号」。按 policy 级注入，模型会当作规则遵循；建议只写 3～10 条短规则，预算 1000 token。',
      resolver: 'agent_doc',
      refKey: 'soul',
      priority: 20,
      maxTokens: 1000,
      trustLevel: 'policy',
      trustHint: '可作为规则遵循',
      enabled: true,
    },
    {
      key: 'agents_guide',
      title: 'Agents Guide',
      description: '每个 Agent 自己的工作指南，例如工具调用时机、引用怎么标 [n]、回答分段结构。按 policy 级注入，模型会当作规则遵循；内容保存在当前 Agent 名下，修改只影响这个 Agent。',
      resolver: 'agent_doc',
      refKey: 'agents_guide',
      priority: 30,
      maxTokens: 2000,
      trustLevel: 'policy',
      trustHint: '可作为规则遵循',
      enabled: true,
    },
    {
      key: 'skills_snapshot',
      title: 'Skills Snapshot',
      description: '按当前 Agent 的工具白名单实时生成能力快照，不落库正文；随工具配置变化自动更新。按 generated 级注入，作为能力清单，仅作事实参考，不作为规则或指令执行。',
      resolver: 'generated',
      refKey: 'skills_snapshot',
      priority: 40,
      maxTokens: 1200,
      trustLevel: 'generated',
      trustHint: '能力清单，仅作事实参考',
      enabled: true,
    },
  ],
  user: [
    {
      key: 'user_profile',
      title: 'User Profile',
      description: '目标用户的稳定事实与偏好，例如称呼、语言、职业、常用术语。内容由当前 Agent 维护，注入时标为 user data，模型只当事实参考，不把它当指令执行。',
      resolver: 'agent_doc',
      refKey: 'user_profile',
      priority: 50,
      maxTokens: 1200,
      trustLevel: 'data',
      trustHint: '仅作事实参考，不作为指令执行',
      enabled: true,
    },
  ],
  memory: [
    {
      key: 'long_term_memory',
      title: 'Long-term Memory',
      description: '跨会话保留的稳定记忆，例如用户反复提到的长期目标或项目背景。后端写入链路尚未实现，这里只是预留配置位，默认关闭；后续阶段实现后会自动按这里配置的优先级和 2000 token 预算注入。',
      resolver: 'memory',
      refKey: 'long_term_memory',
      priority: 60,
      maxTokens: 2000,
      trustLevel: 'data',
      trustHint: '仅作事实参考，不作为指令执行',
      enabled: false,
    },
  ],
}

/** 目标拼接顺序；旧库还没跑迁移时，靠旧 priority 识别出需要临时纠正的显示顺序 */
const CONTEXT_ORDER_KEYS = [
  'identity',
  'soul',
  'agents_guide',
  'skills_snapshot',
  'user_profile',
  'long_term_memory',
]
const LEGACY_CONTEXT_PRIORITY: Record<string, number> = {
  skills_snapshot: 10,
  soul: 20,
  identity: 30,
  agents_guide: 40,
  user_profile: 50,
  long_term_memory: 60,
}

function sortContextDrafts(drafts: ContextDraft[]): ContextDraft[] {
  const relevant = drafts.filter((d) => d.key in LEGACY_CONTEXT_PRIORITY)
  const looksLegacy =
    relevant.length > 0 &&
    relevant.every((d) => d.priority === LEGACY_CONTEXT_PRIORITY[d.key])
  return drafts.slice().sort((a, b) => {
    if (looksLegacy) {
      const ai = CONTEXT_ORDER_KEYS.indexOf(a.key)
      const bi = CONTEXT_ORDER_KEYS.indexOf(b.key)
      const ao = ai < 0 ? CONTEXT_ORDER_KEYS.length : ai
      const bo = bi < 0 ? CONTEXT_ORDER_KEYS.length : bi
      if (ao !== bo) return ao - bo
    }
    return a.priority - b.priority || a.localId - b.localId
  })
}

const contextDrafts = ref<ContextDraft[]>([])
const agentContextDocs = ref<AgentContextDocDto[]>([])
let contextDraftSeq = 0

interface ContextGroup {
  key: 'agent' | 'user' | 'memory'
  label: string
  description: string
  addResolver: ContextResolver
  drafts: ContextDraft[]
}

const USER_CONTEXT_KEYS = ['user_profile']
const MEMORY_CONTEXT_KEYS = ['long_term_memory']

const contextGroups = computed<ContextGroup[]>(() => [
  {
    key: 'agent',
    label: 'Agent 上下文',
    description: 'Agent 自己的规则与能力快照；Agent 文档可直接编辑内容。',
    addResolver: 'agent_doc',
    drafts: contextDrafts.value.filter(
      (d) => !USER_CONTEXT_KEYS.includes(d.key) && !MEMORY_CONTEXT_KEYS.includes(d.key),
    ),
  },
  {
    key: 'user',
    label: '用户上下文',
    description: '目标用户的画像与偏好；作为事实参考注入，不作为规则遵循。',
    addResolver: 'agent_doc',
    drafts: contextDrafts.value.filter((d) => USER_CONTEXT_KEYS.includes(d.key)),
  },
  {
    key: 'memory',
    label: '长期记忆',
    description: '跨会话记忆；输入框失焦后自动保存。',
    addResolver: 'memory',
    drafts: contextDrafts.value.filter(
      (d) => MEMORY_CONTEXT_KEYS.includes(d.key) || d.resolver === 'memory',
    ),
  },
])

const contextPickerGroup = ref<'agent' | 'user' | 'memory' | null>(null)
const activePresets = computed(() =>
  contextPickerGroup.value ? CONTEXT_PRESETS[contextPickerGroup.value] : [],
)
const contextPickerLabel = computed(
  () => contextGroups.value.find((g) => g.key === contextPickerGroup.value)?.label ?? '',
)
const generatingContext = ref<number | null>(null)
const contextGenerateError = ref('')
const contextSaving = ref<Record<'agent' | 'user' | 'memory', boolean>>({
  agent: false,
  user: false,
  memory: false,
})
const contextSaved = ref<Record<'agent' | 'user' | 'memory', string>>({
  agent: '',
  user: '',
  memory: '',
})
/** 上下文拼接顺序：拖动调整 contextDrafts 的数组顺序，保存时写回 priority */
const orderDraggingId = ref<number | null>(null)
const orderDropIndex = ref<number | null>(null)
const orderDirty = ref(false)
const orderSaving = ref(false)
const orderSaved = ref('')
const orderError = ref('')
const memoryDrafts = ref<AgentMemoryDto[]>([])

const GENERATE_LABELS: Record<ContextGenerateKind, string> = {
  soul: '自动生成人格',
  identity: '自动生成身份',
  agents_guide: '自动生成指南',
  user_profile: '自动生成用户资料',
}

function resetAgentForm() {
  agentEditingId.value = null
  agKey.value = ''
  agName.value = ''
  agDescription.value = ''
  agToolMode.value = 'all'
  agToolNames.value = []
  agPrompt.value = ''
  agPromptNote.value = ''
  systemPromptError.value = ''
  adminPrompts.value = []
  contextDrafts.value = []
  agentContextDocs.value = []
  memoryDrafts.value = []
  orderDirty.value = false
  orderSaved.value = ''
  orderError.value = ''
  agentSaved.value = ''
  agentError.value = ''
}

async function loadAdminAgentData() {
  if (!isAdmin.value) return
  agentLoading.value = true
  agentError.value = ''
  try {
    const [list, tools] = await Promise.all([
      listAgents(true),
      listTools(),
    ])
    adminAgents.value = list
    agentTools.value = tools
  } catch (e) {
    agentError.value = e instanceof Error ? e.message : '加载 Agent 配置失败'
  } finally {
    agentLoading.value = false
  }
}

async function loadAgentPrompts(id: number) {
  try {
    adminPrompts.value = await listAgentPrompts(id)
  } catch {
    adminPrompts.value = []
  }
}

async function loadAgentContext(agentId: number) {
  contextGenerateError.value = ''
  try {
    const [bindings, docs, memories] = await Promise.all([
      listAgentBindings(agentId),
      listAgentDocs(agentId),
      listAgentMemories(agentId),
    ])
    agentContextDocs.value = docs
    memoryDrafts.value = memories
    contextDrafts.value = sortContextDrafts(
      bindings.map((b) => {
        const refKey = b.ref_key || b.key
        const doc =
          docs.find((d) => d.agent_id === agentId && d.key === refKey) ?? null
        return {
          localId: ++contextDraftSeq,
          bindingId: b.id,
          docId: doc?.id ?? null,
          key: b.key,
          title: b.title,
          resolver: b.resolver,
          refKey,
          content: doc?.content ?? '',
          enabled: b.enabled,
          priority: b.priority,
          maxTokens: b.max_tokens,
          trustLevel: b.trust_level,
          trustHint: b.trust_hint,
          globalDoc: doc?.agent_id === null,
        }
      }),
    )
    // 这两个分段不依赖手动添加：Skills Snapshot 由工具注册表生成，Long-term Memory 由记忆列表供数。
    // 若 Agent 还没有对应 binding，补一条草稿，保证它们始终出现在拼接顺序列表里。
    for (const key of ['skills_snapshot', 'long_term_memory']) {
      if (contextDrafts.value.some((d) => d.key === key)) continue
      const preset =
        CONTEXT_PRESETS.agent.find((p) => p.key === key) ??
        CONTEXT_PRESETS.memory.find((p) => p.key === key)
      if (!preset) continue
      contextDrafts.value.push({
        localId: ++contextDraftSeq,
        bindingId: null,
        docId: null,
        key: preset.key,
        title: preset.title,
        resolver: preset.resolver,
        refKey: preset.refKey,
        content: '',
        enabled: preset.enabled,
        priority: preset.priority,
        maxTokens: preset.maxTokens,
        trustLevel: preset.trustLevel,
        trustHint: preset.trustHint,
        globalDoc: false,
      })
    }
    contextDrafts.value = sortContextDrafts(contextDrafts.value)
    orderDirty.value = false
    orderSaved.value = ''
    orderError.value = ''
  } catch (e) {
    agentContextDocs.value = []
    contextDrafts.value = []
    memoryDrafts.value = []
    contextGenerateError.value = e instanceof Error ? `加载上下文失败：${e.message}` : '加载上下文失败'
  }
}

function addPresetContext(preset: ContextPreset) {
  if (contextDrafts.value.some((d) => d.key === preset.key)) return
  const agentId = agentEditingId.value
  const doc =
    agentContextDocs.value.find((d) => d.agent_id === agentId && d.key === preset.refKey) ?? null
  contextDrafts.value.push({
    localId: ++contextDraftSeq,
    bindingId: null,
    docId: doc?.id ?? null,
    key: preset.key,
    title: preset.title,
    resolver: preset.resolver,
    refKey: preset.refKey,
    content: doc?.content ?? '',
    enabled: preset.enabled,
    priority: preset.priority,
    maxTokens: preset.maxTokens,
    trustLevel: preset.trustLevel,
    trustHint: preset.trustHint,
    globalDoc: doc?.agent_id === null,
  })
  contextPickerGroup.value = null
}

function presetDescription(draft: ContextDraft): string {
  for (const presets of Object.values(CONTEXT_PRESETS)) {
    const preset = presets.find((p) => p.key === draft.key)
    if (preset) return preset.description
  }
  return '自定义上下文分段。'
}

function generateButtonLabel(key: string): string {
  return GENERATE_LABELS[key as ContextGenerateKind] ?? '自动生成'
}

async function generateDraftContent(draft: ContextDraft) {
  const kind = draft.key as ContextGenerateKind
  if (!(kind in GENERATE_LABELS)) return
  generatingContext.value = draft.localId
  contextGenerateError.value = ''
  try {
    const result = await generateContextContent({
      kind,
      agent_id: agentEditingId.value,
      current: draft.content,
    })
    // draft 来自 computed 过滤后的数组引用；通过原数组按 localId 回写，确保响应式更新
    const target = contextDrafts.value.find((item) => item.localId === draft.localId)
    const content = typeof result?.content === 'string' ? result.content : ''
    if (target) target.content = content
    else draft.content = content
    agentSaved.value = ''
  } catch (e) {
    contextGenerateError.value = e instanceof Error ? e.message : '生成失败'
  } finally {
    generatingContext.value = null
  }
}

async function generateSystemPrompt() {
  if (systemPromptGenerating.value) return
  systemPromptGenerating.value = true
  systemPromptError.value = ''
  try {
    const result = await composeSystemPrompt({
      prompt: agPrompt.value,
      agent_id: agentEditingId.value,
    })
    agPrompt.value = result.content
    agentSaved.value = ''
  } catch (e) {
    systemPromptError.value = e instanceof Error ? e.message : '生成系统提示词失败'
  } finally {
    systemPromptGenerating.value = false
  }
}

/** 去除空行后比较：只增删空行不算内容变化，避免无意义地重建 system_prompt */
function sameContentIgnoringBlankLines(a: string, b: string): boolean {
  const strip = (s: string) =>
    (s || '')
      .split(/\r?\n/)
      .filter((line) => line.trim() !== '')
      .join('\n')
  return strip(a) === strip(b)
}

/** 分段相对已落库文档是否有实质内容变化；新增空白分段返回 false */
function draftHasMeaningfulChange(draft: ContextDraft): boolean {
  if (draft.resolver !== 'agent_doc') return true
  const doc = agentContextDocs.value.find((d) => d.id === draft.docId)
  return !sameContentIgnoringBlankLines(doc?.content ?? '', draft.content)
}

/** 上下文保存后重新生成提示词并落库，保证 agent_prompts.hash 与上下文同步 */
async function regenerateAndSavePrompt(agentId: number, note: string) {
  try {
    const result = await composeSystemPrompt({
      prompt: agPrompt.value,
      agent_id: agentId,
    })
    agPrompt.value = result.content
    await createAgentPrompt(agentId, {
      system_prompt: result.content,
      note,
      activate: true,
    })
    await loadAgentPrompts(agentId)
    void loadChatAgents(true)
  } catch (e) {
    systemPromptError.value = e instanceof Error ? e.message : '上下文变更后生成提示词失败'
  }
}

async function saveSystemPromptPreview() {
  const id = agentEditingId.value
  if (id === null || !agPrompt.value.trim() || systemPromptSaving.value) return
  systemPromptSaving.value = true
  systemPromptError.value = ''
  try {
    await createAgentPrompt(id, {
      system_prompt: agPrompt.value,
      note: agPromptNote.value.trim() || undefined,
      activate: true,
    })
    await loadAdminAgentData()
    await loadAgentPrompts(id)
    void loadChatAgents(true)
    agentSaved.value = '已保存系统提示词并发布新版本'
    agPromptNote.value = ''
  } catch (e) {
    systemPromptError.value = e instanceof Error ? e.message : '保存系统提示词失败'
  } finally {
    systemPromptSaving.value = false
  }
}

function removeContextDraft(localId: number) {
  contextDrafts.value = contextDrafts.value.filter((d) => d.localId !== localId)
}

function moveContextDraft(from: number, to: number) {
  const drafts = contextDrafts.value
  if (from < 0 || to < 0 || from >= drafts.length || to >= drafts.length || from === to) return
  const reordered = drafts.slice()
  const [moved] = reordered.splice(from, 1)
  reordered.splice(to, 0, moved)
  contextDrafts.value = reordered
  orderDirty.value = true
  orderSaved.value = ''
  orderError.value = ''
}

function onOrderDragStart(event: DragEvent, index: number) {
  orderDraggingId.value = contextDrafts.value[index]?.localId ?? null
  orderDropIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(index))
  }
}

function onOrderDragOver(event: DragEvent, index: number) {
  if (orderDraggingId.value === null) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  orderDropIndex.value = index
}

function onOrderDrop(event: DragEvent, index: number) {
  if (orderDraggingId.value === null) return
  event.preventDefault()
  const from = contextDrafts.value.findIndex((d) => d.localId === orderDraggingId.value)
  moveContextDraft(from, index)
  onOrderDragEnd()
}

function onOrderDragEnd() {
  orderDraggingId.value = null
  orderDropIndex.value = null
}

/** 本地草稿用负 id 标识，失焦有内容时再落库 */
let memoryDraftSeq = 0

function addMemoryDraft() {
  const agentId = agentEditingId.value
  if (agentId === null) return
  contextGenerateError.value = ''
  memoryDrafts.value.push({
    id: --memoryDraftSeq,
    agent_id: agentId,
    content: '',
    enabled: true,
    created_at: '',
    updated_at: '',
  })
}

async function updateMemoryContent(memory: AgentMemoryDto, content: string) {
  const agentId = agentEditingId.value
  if (agentId === null) return
  contextGenerateError.value = ''
  const index = memoryDrafts.value.findIndex((m) => m.id === memory.id)
  if (index < 0) return

  const meaningful = !sameContentIgnoringBlankLines(memory.content, content)
  if (!content.trim()) {
    // 失焦仍为空：本地草稿直接丢弃，已落库的清空内容
    if (memory.id < 0) {
      memoryDrafts.value.splice(index, 1)
    } else {
      try {
        const updated = await updateAgentMemory(agentId, memory.id, { content })
        memoryDrafts.value[index] = updated
      } catch (e) {
        contextGenerateError.value = e instanceof Error ? e.message : '保存记忆失败'
      }
    }
    return
  }

  try {
    const updated =
      memory.id < 0
        ? await createAgentMemory(agentId, content)
        : await updateAgentMemory(agentId, memory.id, { content })
    memoryDrafts.value[index] = updated
    // 只增删空行不算实质变化
    if (meaningful) {
      void regenerateAndSavePrompt(agentId, '记忆内容变更后自动生成')
    }
  } catch (e) {
    contextGenerateError.value = e instanceof Error ? e.message : '保存记忆失败'
  }
}

async function removeMemoryDraft(memory: AgentMemoryDto) {
  const agentId = agentEditingId.value
  if (agentId === null) return
  contextGenerateError.value = ''
  const index = memoryDrafts.value.findIndex((m) => m.id === memory.id)
  if (index < 0) return

  try {
    // 本地草稿未落库，直接移除；空白记忆也不触发重建
    const meaningful = !!memory.content.trim()
    if (memory.id >= 0) {
      await deleteAgentMemory(agentId, memory.id)
    }
    memoryDrafts.value.splice(index, 1)
    if (meaningful) {
      void regenerateAndSavePrompt(agentId, '记忆删除后自动生成')
    }
  } catch (e) {
    contextGenerateError.value = e instanceof Error ? e.message : '删除记忆失败'
  }
}

async function saveContextGroup(groupKey: 'agent' | 'user' | 'memory') {
  if (agentEditingId.value === null || contextSaving.value[groupKey]) return
  const drafts = contextGroups.value.find((g) => g.key === groupKey)?.drafts ?? []
  if (!drafts.length) return
  contextSaving.value[groupKey] = true
  contextSaved.value[groupKey] = ''
  contextGenerateError.value = ''
  try {
    // 全部是空白分段时跳过重建，避免新增空分段就发布新版本
    const meaningful = drafts.some((d) => draftHasMeaningfulChange(d))
    await saveAgentContexts(agentEditingId.value, drafts)
    contextSaved.value[groupKey] = '已保存'
    if (meaningful) {
      await regenerateAndSavePrompt(agentEditingId.value, '上下文保存后自动生成')
    }
  } catch (e) {
    contextGenerateError.value = e instanceof Error ? e.message : '保存上下文失败'
  } finally {
    contextSaving.value[groupKey] = false
  }
}

async function saveAgentContexts(agentId: number, drafts: ContextDraft[] = contextDrafts.value) {
  // 保存其它设置后会重新拉取分段；保留当前拖动顺序，避免未保存的顺序被覆盖
  const previousOrder = contextDrafts.value.map((d) => d.key)
  const keepOrderDirty = orderDirty.value
  for (const draft of drafts) {
    const key = draft.key.trim()
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(key)) {
      throw new Error(`上下文分段 key 不合法：${key || '(空)'}`)
    }
    const refKey = draft.refKey.trim() || key
    const fields = {
      title: draft.title.trim(),
      resolver: draft.resolver,
      ref_key: refKey,
      enabled: draft.enabled,
      priority: draft.priority,
      max_tokens: draft.maxTokens,
      trust_level: draft.trustLevel,
      trust_hint: draft.trustHint,
    }
    if (draft.bindingId === null) {
      const created = await createAgentBinding(agentId, { key, ...fields })
      draft.bindingId = created.id
    } else {
      await updateAgentBinding(draft.bindingId, fields)
    }
    if (draft.resolver === 'agent_doc') {
      if (draft.docId !== null) {
        await updateAgentDoc(draft.docId, { content: draft.content })
      } else {
        const createdDoc = await createAgentDoc({
          agent_id: agentId,
          key: refKey,
          title: draft.title.trim(),
          content: draft.content,
        })
        draft.docId = createdDoc.id
      }
    }
  }
  await loadAgentContext(agentId)
  const byKey = new Map(contextDrafts.value.map((d) => [d.key, d]))
  const restored = previousOrder
    .map((key) => byKey.get(key))
    .filter((d): d is ContextDraft => d !== undefined)
  if (restored.length === contextDrafts.value.length) {
    contextDrafts.value = restored
    orderDirty.value = keepOrderDirty
  }
}

async function saveContextOrder() {
  if (agentEditingId.value === null || orderSaving.value || !contextDrafts.value.length) return
  orderSaving.value = true
  orderSaved.value = ''
  orderError.value = ''
  try {
    contextDrafts.value.forEach((draft, index) => {
      draft.priority = (index + 1) * 10
    })
    await saveAgentContexts(agentEditingId.value, contextDrafts.value)
    orderDirty.value = false
    orderSaved.value = '已保存拼接顺序'
    await regenerateAndSavePrompt(agentEditingId.value, '排序调整后自动生成')
  } catch (e) {
    orderError.value = e instanceof Error ? e.message : '保存拼接顺序失败'
  } finally {
    orderSaving.value = false
  }
}

async function editAgent(agent: AgentDto) {
  agentEditingId.value = agent.id
  agKey.value = agent.agent_key
  agName.value = agent.name
  agDescription.value = agent.description
  agToolMode.value = agent.tool_names === null ? 'all' : 'picked'
  agToolNames.value = [...(agent.tool_names ?? [])]
  systemPromptError.value = ''
  agentSaved.value = ''
  agentError.value = ''
  agentFormOpen.value = true
  pushView()
  await loadAgentPrompts(agent.id)
  const active = adminPrompts.value.find((p) => p.version === agent.active_prompt_version)
  agPrompt.value = active?.system_prompt ?? ''
  agPromptNote.value = active?.note ?? ''
  void loadAgentContext(agent.id)
}

function toggleAgentTool(name: string) {
  const i = agToolNames.value.indexOf(name)
  if (i >= 0) agToolNames.value.splice(i, 1)
  else agToolNames.value.push(name)
}

async function saveAgent() {
  agentSaved.value = ''
  agentError.value = ''
  const key = agKey.value.trim()
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(key)) {
    agentError.value = 'agent_key 只能用小写字母、数字和下划线，且要以字母开头'
    return
  }
  const toolNames = agToolMode.value === 'all' ? null : agToolNames.value
  try {
    if (agentEditingId.value === null) {
      const created = await createAgent({
        agent_key: key,
        name: agName.value.trim(),
        description: agDescription.value.trim(),
        tool_names: toolNames,
        system_prompt: undefined,
      })
      agentEditingId.value = created.id
    } else {
      await updateAgent(agentEditingId.value, {
        name: agName.value.trim(),
        description: agDescription.value.trim(),
        tool_names: toolNames,
        is_active: true,
      })
    }
    if (agentEditingId.value !== null) {
      await saveAgentContexts(agentEditingId.value)
    }
    await loadAdminAgentData()
    await loadAgentPrompts(agentEditingId.value)
    void loadChatAgents(true)
    agentSaved.value = '已保存 Agent 配置及上下文分段'
    showSaveToast(agentSaved.value)
    orderDirty.value = false
    agPrompt.value = ''
    agPromptNote.value = ''
  } catch (e) {
    agentError.value = e instanceof Error ? e.message : '保存 Agent 失败'
  }
}

async function removeAgent(agentId: number | null = agentEditingId.value) {
  if (agentId === null) return
  const target = adminAgents.value.find((a) => a.id === agentId)
  if (!target || !window.confirm(`确认删除 Agent「${target.name || target.agent_key}」？`)) return
  agentError.value = ''
  try {
    await deleteAgent(target.id)
    if (agentFormOpen.value) {
      resetAgentForm()
      goBack()
    }
    await loadAdminAgentData()
    void loadChatAgents(true)
  } catch (e) {
    agentError.value = e instanceof Error ? e.message : '删除 Agent 失败'
  }
}

async function activateVersion(version: number) {
  if (agentEditingId.value === null) return
  agentError.value = ''
  try {
    await activateAgentPrompt(agentEditingId.value, version)
    await loadAdminAgentData()
    await loadAgentPrompts(agentEditingId.value)
    const active = adminPrompts.value.find((p) => p.version === version)
    agPrompt.value = active?.system_prompt ?? ''
    agPromptNote.value = active?.note ?? ''
    void loadChatAgents(true)
    agentSaved.value = `已切换到 v${version}`
  } catch (e) {
    agentError.value = e instanceof Error ? e.message : '切换提示词版本失败'
  }
}

watch(nav, (value) => {
  if (value === 'agent' && isAdmin.value) void loadAdminAgentData()
  if (value === 'model') {
    // 切回模型页时回到列表视图；表单只在点「新增/编辑」后出现
    formOpen.value = false
    // 模型配置只在登录时由 LeftRail 拉过一次，那次失败或没赶上时序就会一直空着；
    // 切回模型页主动重拉，避免误显示"还没有接入模型"
    if (isAdmin.value) void load()
  }
})

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
  contextSize.value = DEFAULT_CONTEXT_SIZE
}

function loadDraft() {
  const target = providers.value.find((p) => p.id === activeId.value) ?? providers.value[0]
  saved.value = false
  saveError.value = ''
  testResult.value = null
  logoutConfirm.value = false
  nameError.value = false
  // 默认始终只展示列表；即使一行都没有，也由用户点「+ 新增模型」再展开
  formOpen.value = false
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
  contextSize.value = normalizeContextSize(p.context_size)
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
    // 打开设置时主动拉一次：避免只在登录时拉的那次失败后列表一直空着，
    // 也确保管理员看到的是服务端最新配置
    if (isAdmin.value) void load()
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
    context_size: contextSize.value,
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

/** 账户页退出登录：两步确认，避免误点；离开账户页时重置 */
const logoutConfirm = ref(false)

function onLogout() {
  if (!logoutConfirm.value) {
    logoutConfirm.value = true
    return
  }
  logout()
  close()
}

/* ---------------- 账户：昵称 / 头像 / 密码 ---------------- */
const profileEditing = ref(false)
const nicknameDraft = ref('')
const avatarDraft = ref('')
const profileSaving = ref(false)
const profileError = ref('')
const profileSaved = ref('')
const avatarInput = ref<HTMLInputElement | null>(null)

function startEditProfile() {
  nicknameDraft.value = user.value?.nickname || user.value?.username || ''
  avatarDraft.value = user.value?.avatar || ''
  profileError.value = ''
  profileSaved.value = ''
  profileEditing.value = true
}

function cancelEditProfile() {
  profileEditing.value = false
  profileError.value = ''
}

function pickAvatar() {
  avatarInput.value?.click()
}

/** 先把图片压到 160×160 的 JPEG，控制 data URL 体积（后端限量 2MB） */
function onAvatarPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    profileError.value = '请选择图片文件'
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    profileError.value = '原图不能超过 5MB'
    return
  }
  profileError.value = ''
  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      const max = 160
      const scale = Math.min(max / img.width, max / img.height, 1)
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(img.width * scale))
      canvas.height = Math.max(1, Math.round(img.height * scale))
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        profileError.value = '图片处理失败，请重试'
        return
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      avatarDraft.value = canvas.toDataURL('image/jpeg', 0.85)
    }
    img.src = String(reader.result)
  }
  reader.readAsDataURL(file)
  input.value = ''
}

async function saveProfile() {
  if (!nicknameDraft.value.trim()) {
    profileError.value = '昵称不能为空'
    return
  }
  profileSaving.value = true
  profileError.value = ''
  profileSaved.value = ''
  try {
    setUser(
      await authApi.updateProfile({
        nickname: nicknameDraft.value.trim(),
        avatar: avatarDraft.value,
      }),
    )
    profileEditing.value = false
    profileSaved.value = '资料已更新'
  } catch (e) {
    profileError.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    profileSaving.value = false
  }
}

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const passwordSaving = ref(false)
const passwordError = ref('')
const passwordSaved = ref('')
/** 账户页内的二级视图：点「密码修改」才展开三个输入框 */
const passwordView = ref(false)

/* ---------------- 设置内导航历史：顶部前进 / 后退 ---------------- */
interface SettingsView {
  nav: NavKey
  password: boolean
  agentForm: boolean
}
const viewHistory = ref<SettingsView[]>([
  { nav: 'model', password: false, agentForm: false },
])
const viewIndex = ref(0)
const hasViewHistory = computed(() => viewHistory.value.length > 1)
const canGoBack = computed(() => viewIndex.value > 0)
const canGoForward = computed(() => viewIndex.value < viewHistory.value.length - 1)

// 重新打开设置时回到当前页签的一级视图：否则会残留上次的二级页面和历史记录
watch(open, (v) => {
  if (!v) return
  viewHistory.value = [{ nav: nav.value, password: false, agentForm: false }]
  viewIndex.value = 0
  passwordView.value = false
  agentFormOpen.value = false
})

function restoreView(v: SettingsView) {
  nav.value = v.nav
  passwordView.value = v.password
  agentFormOpen.value = v.agentForm
}

function pushView() {
  viewHistory.value = [
    ...viewHistory.value.slice(0, viewIndex.value + 1),
    {
      nav: nav.value,
      password: passwordView.value,
      agentForm: agentFormOpen.value,
    },
  ]
  viewIndex.value = viewHistory.value.length - 1
}

function goNav(next: NavKey) {
  if (nav.value === next && !passwordView.value && !agentFormOpen.value) return
  nav.value = next
  passwordView.value = false
  agentFormOpen.value = false
  pushView()
}

function openPassword() {
  // 每次进入都从空表单开始：顶层后退按钮不会走 backToAccount，得在这里清掉旧输入
  passwordError.value = ''
  oldPassword.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
  passwordView.value = true
  pushView()
}

function openAgentForm() {
  resetAgentForm()
  agentFormOpen.value = true
  pushView()
}

function goBack() {
  if (!canGoBack.value) {
    passwordView.value = false
    agentFormOpen.value = false
    return
  }
  viewIndex.value -= 1
  restoreView(viewHistory.value[viewIndex.value])
}

function goForward() {
  if (!canGoForward.value) return
  viewIndex.value += 1
  restoreView(viewHistory.value[viewIndex.value])
}

function backToAccount() {
  goBack()
  passwordError.value = ''
  oldPassword.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
}

// 底部保存按钮已移除：保留函数以便恢复，当前模板不再触发
void saveAgent


async function changePassword() {
  passwordError.value = ''
  passwordSaved.value = ''
  if (!oldPassword.value || !newPassword.value) {
    passwordError.value = '请填写当前密码和新密码'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = '两次输入的新密码不一致'
    return
  }
  passwordSaving.value = true
  try {
    await authApi.changePassword({
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    passwordSaved.value = '密码已修改，请用新密码重新登录'
    // 服务端已吊销全部 refresh，本地登录态一并作废；不自动关弹窗，让用户看到提示
    await logout()
  } catch (e) {
    passwordError.value = e instanceof Error ? e.message : '修改失败'
  } finally {
    passwordSaving.value = false
  }
}

watch(nav, () => {
  logoutConfirm.value = false
  profileEditing.value = false
  profileError.value = ''
  profileSaved.value = ''
  passwordError.value = ''
  passwordSaved.value = ''
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
          <div class="flex items-center gap-2">
            <h2 class="text-[16px] font-semibold text-stone-800">设置</h2>
            <template v-if="hasViewHistory">
              <span class="mx-1 h-4 w-px bg-stone-200"></span>
              <button
                type="button"
                @click="goBack"
                :disabled="!canGoBack"
                class="h-7 w-7 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition"
                title="后退"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
              </button>
              <button
                type="button"
                @click="goForward"
                :disabled="!canGoForward"
                class="h-7 w-7 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed transition"
                title="前进"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
              </button>
            </template>
          </div>
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
              v-for="item in visibleNavItems"
              :key="item.key"
              type="button"
              @click="goNav(item.key)"
              class="w-full h-9 flex items-center gap-2.5 rounded-lg px-3 text-[13px] transition"
              :class="nav === item.key ? 'bg-stone-100 text-stone-900 font-medium' : 'text-stone-600 hover:bg-stone-100'"
            >
              <!-- 账户 -->
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

                <!-- 上下文大小：按模型窗口裁剪对话历史，避免超长会话把上游撑爆 -->
                <div class="mt-4 flex items-center justify-between gap-3">
                  <span class="text-[12.5px] font-medium text-stone-600">
                    上下文大小
                    <span class="block text-[11px] font-normal text-stone-400">对话历史按此窗口裁剪，超出部分从最早轮次丢弃</span>
                  </span>
                  <select
                    v-model.number="contextSize"
                    class="h-9 shrink-0 rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] text-stone-800 outline-none focus:border-stone-400"
                  >
                    <option v-for="opt in CONTEXT_SIZES" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                </div>

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

            <!-- 通用设置 -->
            <template v-else-if="nav === 'general'">
              <h3 class="text-[17px] font-semibold text-stone-800">通用设置</h3>
              <p class="mt-1 text-[12.5px] text-stone-400">
                外观偏好仅保存在当前浏览器，不影响其他设备。
              </p>

              <div class="mt-5 rounded-xl border border-stone-200 px-4 py-3.5">
                <div class="flex items-center justify-between gap-4">
                  <div class="min-w-0">
                    <p class="text-[13px] font-medium text-stone-800">主题</p>
                    <p class="mt-0.5 text-[11.5px] text-stone-400">选择浅色、深色，或跟随系统外观自动切换</p>
                  </div>
                  <div class="inline-flex shrink-0 rounded-lg border border-stone-200 bg-stone-50 p-0.5">
                    <button
                      v-for="opt in themeOptions"
                      :key="opt.value"
                      type="button"
                      @click="setThemeMode(opt.value)"
                      class="px-3 py-1.5 rounded-md text-[12px] transition"
                      :class="themeMode === opt.value
                        ? 'bg-white text-stone-900 font-medium shadow-sm'
                        : 'text-stone-500 hover:text-stone-800'"
                    >
                      {{ opt.label }}
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 账户 -->
            <template v-else-if="nav === 'account'">
              <h3 class="text-[17px] font-semibold text-stone-800">账户</h3>
              <p class="mt-1 text-[12.5px] text-stone-400">
                管理个人资料与登录密码，余额与用量统计即将开放。
              </p>

              <p v-if="passwordSaved" class="mt-4 rounded-lg bg-green-50 px-3 py-2 text-[12px] text-green-700">{{ passwordSaved }}</p>
              <template v-if="isLoggedIn">
                <template v-if="!passwordView">
                <!-- 个人资料 -->
                <div class="mt-4 rounded-xl border border-stone-200">
                  <div class="flex items-center gap-3 px-4 py-3.5">
                    <img
                      v-if="user?.avatar"
                      :src="user.avatar"
                      alt="头像"
                      class="h-11 w-11 shrink-0 rounded-full object-cover"
                    />
                    <span
                      v-else
                      class="h-11 w-11 shrink-0 rounded-full bg-gradient-to-br from-stone-300 to-stone-500 grid place-items-center text-[14px] font-semibold text-white"
                    >
                      {{ (user?.nickname || user?.username || '?').charAt(0).toUpperCase() }}
                    </span>
                    <span class="min-w-0 flex-1 leading-tight">
                      <span class="block text-[13.5px] font-semibold text-stone-800 truncate">{{ user?.nickname || user?.username }}</span>
                      <span class="block text-[11.5px] text-stone-500 truncate">{{ user?.username }} · {{ user?.email }}</span>
                    </span>
                    <button
                      v-if="!profileEditing"
                      type="button"
                      @click="startEditProfile"
                      class="h-8 px-3 shrink-0 rounded-lg border border-stone-200 text-[12.5px] text-stone-600 hover:bg-stone-50 transition"
                    >
                      编辑资料
                    </button>
                  </div>

                  <div v-if="profileEditing" class="border-t border-stone-100 px-4 py-3.5 space-y-3">
                    <p v-if="profileError" class="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{{ profileError }}</p>
                    <div>
                      <p class="mb-1.5 text-[12px] text-stone-500">头像</p>
                      <div class="flex items-center gap-3">
                        <button
                          type="button"
                          @click="pickAvatar"
                          class="h-14 w-14 shrink-0 overflow-hidden rounded-full border border-stone-200 hover:border-stone-400 transition"
                          title="点击更换头像"
                        >
                          <img v-if="avatarDraft" :src="avatarDraft" alt="头像预览" class="h-full w-full object-cover" />
                          <span v-else class="h-full w-full grid place-items-center bg-stone-100 text-[11px] text-stone-400">上传</span>
                        </button>
                        <span class="text-[11.5px] text-stone-400">点击左侧更换，图片会自动压缩</span>
                      </div>
                      <input
                        ref="avatarInput"
                        type="file"
                        accept="image/png,image/jpeg,image/gif,image/webp"
                        class="hidden"
                        @change="onAvatarPicked"
                      />
                    </div>
                    <div>
                      <label for="nickname-draft" class="mb-1.5 block text-[12px] text-stone-500">昵称</label>
                      <input
                        id="nickname-draft"
                        v-model="nicknameDraft"
                        type="text"
                        maxlength="64"
                        placeholder="请输入昵称"
                        class="h-9 w-full rounded-lg border border-stone-200 px-3 text-[13px] text-stone-800 outline-none focus:border-stone-400"
                      />
                    </div>
                    <div class="flex justify-end gap-2">
                      <button
                        type="button"
                        @click="cancelEditProfile"
                        class="h-8 px-3 rounded-lg border border-stone-200 text-[12.5px] text-stone-600 hover:bg-stone-50 transition"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        @click="saveProfile"
                        :disabled="profileSaving"
                        class="h-8 px-4 rounded-lg bg-stone-800 text-[12.5px] text-white hover:bg-stone-700 disabled:opacity-50 transition"
                      >
                        {{ profileSaving ? '保存中…' : '保存' }}
                      </button>
                    </div>
                  </div>
                  <p v-if="profileSaved && !profileEditing" class="border-t border-stone-100 px-4 py-2 text-[11.5px] text-green-600">{{ profileSaved }}</p>
                </div>

                <!-- 密码修改入口 -->
                <button
                  type="button"
                  @click="openPassword"
                  class="mt-4 w-full flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-4 py-3.5 text-left hover:bg-stone-50 transition"
                >
                  <span class="min-w-0">
                    <span class="block text-[13px] font-medium text-stone-800">密码修改</span>
                    <span class="block text-[11.5px] text-stone-400">更新登录密码，修改后需重新登录</span>
                  </span>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-stone-400"><path d="m9 18 6-6 6-6" /></svg>
                </button>

                <div class="mt-4 flex justify-end">
                  <button
                    type="button"
                    @click="onLogout"
                    class="h-8 px-4 rounded-lg border text-[13px] transition"
                    :class="
                      logoutConfirm
                        ? 'border-red-200 bg-red-50 text-red-600 hover:bg-red-100'
                        : 'border-stone-200 text-stone-600 hover:border-red-200 hover:text-red-600'
                    "
                  >
                    {{ logoutConfirm ? '确认退出' : '退出登录' }}
                  </button>
                </div>
                </template>

                <!-- 二级：密码修改 -->
                <template v-else>
                  <h4 class="mt-4 text-[13px] font-medium text-stone-800">密码修改</h4>
                  <div class="mt-4 space-y-2">
                    <input
                      v-model="oldPassword"
                      type="password"
                      autocomplete="current-password"
                      placeholder="当前密码"
                      class="h-9 w-full rounded-lg border border-stone-200 px-3 text-[13px] text-stone-800 outline-none focus:border-stone-400"
                    />
                    <input
                      v-model="newPassword"
                      type="password"
                      autocomplete="new-password"
                      placeholder="新密码（至少 6 位）"
                      class="h-9 w-full rounded-lg border border-stone-200 px-3 text-[13px] text-stone-800 outline-none focus:border-stone-400"
                    />
                    <input
                      v-model="confirmPassword"
                      type="password"
                      autocomplete="new-password"
                      placeholder="确认新密码"
                      class="h-9 w-full rounded-lg border border-stone-200 px-3 text-[13px] text-stone-800 outline-none focus:border-stone-400"
                    />
                  </div>
                  <p v-if="passwordError" class="mt-2 text-[11.5px] text-red-600">{{ passwordError }}</p>
                  <div class="mt-4 flex justify-end gap-2">
                    <button
                      type="button"
                      @click="backToAccount"
                      class="h-8 px-3 rounded-lg border border-stone-200 text-[12.5px] text-stone-600 hover:bg-stone-50 transition"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      @click="changePassword"
                      :disabled="passwordSaving"
                      class="h-8 px-4 rounded-lg bg-stone-800 text-[12.5px] text-white hover:bg-stone-700 disabled:opacity-50 transition"
                    >
                      {{ passwordSaving ? '提交中…' : '确认修改' }}
                    </button>
                  </div>
                </template>
              </template>
              <p v-else class="mt-4 text-[12.5px] text-stone-400">当前未登录，依赖账户的功能不可用。</p>
            </template>

            <!-- Agent 预设：管理员在线定义 agent / 发布提示词版本 -->
            <template v-else-if="nav === 'agent'">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <h3 class="text-[17px] font-semibold text-stone-800">Agent 预设</h3>
                  <p class="mt-1 text-[12.5px] text-stone-400">
                    管理员维护；每个 agent 可独立配置模型、工具白名单与提示词版本。
                  </p>
                </div>
                <button
                  type="button"
                  @click="openAgentForm"
                  class="h-8 px-3 shrink-0 rounded-lg bg-stone-800 text-[12.5px] text-white hover:bg-stone-700 transition"
                >
                  + 新增 Agent
                </button>
              </div>

              <p v-if="agentError" class="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{{ agentError }}</p>
              <p v-if="agentSaved" class="mt-3 rounded-lg bg-green-50 px-3 py-2 text-[12px] text-green-700">{{ agentSaved }}</p>
              <p v-if="agentLoading" class="mt-3 text-[12px] text-stone-400">加载中…</p>

              <div v-if="!agentFormOpen" class="mt-4 space-y-2">
                <div
                  v-for="a in adminAgents"
                  :key="a.id"
                  @click="editAgent(a)"
                  class="w-full flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-4 py-3 text-left hover:bg-stone-50 transition cursor-pointer"
                >
                  <span class="min-w-0">
                    <span class="block text-[13.5px] font-medium text-stone-800 truncate">
                      {{ a.name || a.agent_key }}
                      <span v-if="!a.is_active" class="ml-1 text-[10.5px] text-stone-400">已停用</span>
                    </span>
                    <span class="block text-[11.5px] text-stone-400 truncate">
                      {{ a.agent_key }} · 提示词 v{{ a.active_prompt_version }}
                    </span>
                  </span>
                  <span class="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      @click.stop="removeAgent(a.id)"
                      class="rounded-lg px-2 py-1 text-[11.5px] text-red-500 hover:bg-red-50 transition"
                      title="删除 Agent"
                    >
                      删除
                    </button>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0 text-stone-400" stroke-linecap="round">
                      <path d="m9 18 6-6-6-6" />
                    </svg>
                  </span>
                </div>
                <p v-if="!adminAgents.length && !agentLoading" class="py-8 text-center text-[12.5px] text-stone-400">还没有 Agent，点右上角新增。</p>
              </div>

              <div v-else class="mt-4 space-y-4">
                <div class="grid grid-cols-2 gap-3">
                  <label class="text-[12px] text-stone-600">
                    agent_key
                    <input
                      v-model="agKey"
                      :disabled="agentEditingId !== null"
                      maxlength="64"
                      placeholder="chat / planner"
                      class="mt-1 h-9 w-full rounded-lg border border-stone-200 px-2.5 text-[12.5px] disabled:bg-stone-50 disabled:text-stone-400"
                    />
                  </label>
                  <label class="text-[12px] text-stone-600">
                    名称
                    <input v-model="agName" maxlength="128" class="mt-1 h-9 w-full rounded-lg border border-stone-200 px-2.5 text-[12.5px]" />
                  </label>
                </div>

                <label class="block text-[12px] text-stone-600">
                  描述
                  <input v-model="agDescription" maxlength="255" class="mt-1 h-9 w-full rounded-lg border border-stone-200 px-2.5 text-[12.5px]" />
                </label>

                <div class="rounded-xl border border-stone-200 p-3">
                  <p class="text-[12.5px] font-medium text-stone-700">工具白名单</p>
                  <div class="mt-2 flex items-center gap-4 text-[12px] text-stone-600">
                    <label class="flex items-center gap-1.5">
                      <input v-model="agToolMode" type="radio" value="all" class="accent-stone-800" />
                      全部工具
                    </label>
                    <label class="flex items-center gap-1.5">
                      <input v-model="agToolMode" type="radio" value="picked" class="accent-stone-800" />
                      仅勾选
                    </label>
                  </div>
                  <div v-if="agToolMode === 'picked'" class="mt-2 flex flex-wrap gap-2">
                    <label
                      v-for="t in agentTools"
                      :key="t.name"
                      class="inline-flex items-center gap-1.5 rounded-lg border border-stone-200 px-2.5 py-1 text-[12px] text-stone-600"
                    >
                      <input type="checkbox" :checked="agToolNames.includes(t.name)" @change="toggleAgentTool(t.name)" class="accent-stone-800" />
                      {{ t.label || t.name }}
                    </label>
                    <p v-if="!agentTools.length" class="text-[12px] text-stone-400">当前没有可用工具</p>
                  </div>
                </div>

                <div class="rounded-xl border border-stone-200 p-3">
                  <p class="text-[12.5px] font-medium text-stone-700">系统提示词</p>
                  <p class="mt-0.5 text-[11.5px] text-stone-400">留空表示不改；填写后会发布一个新版本并自动生效。</p>
                  <textarea
                    v-model="agPrompt"
                    rows="5"
                    maxlength="20000"
                    placeholder="你是……"
                    class="mt-2 w-full resize-y rounded-lg border border-stone-200 px-2.5 py-2 text-[12.5px] leading-[1.6]"
                  />
                  <input
                    v-model="agPromptNote"
                    maxlength="255"
                    placeholder="版本备注（可选）"
                    class="mt-2 h-8 w-full rounded-lg border border-stone-200 px-2.5 text-[12px]"
                  />

                  <div class="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      @click="generateSystemPrompt"
                      :disabled="systemPromptGenerating"
                      class="h-8 px-3 shrink-0 rounded-lg border border-stone-200 bg-white text-[11.5px] text-stone-600 hover:bg-stone-50 disabled:opacity-40 transition"
                    >
                      {{ systemPromptGenerating ? '生成中…' : '生成系统提示词' }}
                    </button>
                    <button
                      v-if="agPrompt.trim()"
                      type="button"
                      @click="saveSystemPromptPreview"
                      :disabled="agentEditingId === null || systemPromptSaving"
                      class="h-8 px-3 shrink-0 rounded-lg bg-stone-800 text-[11.5px] text-white hover:bg-stone-700 disabled:opacity-40 transition"
                    >
                      {{ systemPromptSaving ? '保存中…' : '保存到提示词版本' }}
                    </button>
                    <span v-if="systemPromptError" class="text-[11px] text-red-600">{{ systemPromptError }}</span>
                  </div>
                  <p class="mt-1 text-[10.5px] text-stone-400">
                    生成时会按 Agent 预设里保存的上下文顺序追加分段；提示词留空时只生成日期和分段。保存会发布为新版本并自动启用。
                  </p>
                </div>

                <div class="rounded-xl border border-stone-200 p-3">
                  <div>
                    <p class="text-[12.5px] font-medium text-stone-700">上下文分段</p>
                    <p class="mt-0.5 text-[11.5px] text-stone-400">
                      按优先级注入到系统提示词之后；Agent、用户与长期记忆分开管理，每组独立保存。
                    </p>
                    <p v-if="agentEditingId === null" class="mt-2 text-[11px] text-stone-400">
                      新建 Agent 需先用底部「保存」创建后，才能单独保存上下文。
                    </p>
                    <p v-if="contextGenerateError" class="mt-2 rounded-lg bg-red-50 px-3 py-2 text-[11.5px] text-red-600">
                      {{ contextGenerateError }}
                    </p>
                  </div>

                  <div
                    v-for="group in contextGroups"
                    :key="group.key"
                    class="mt-3 rounded-lg border border-stone-200 bg-stone-50/40 p-3"
                  >
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <p class="text-[12px] font-medium text-stone-700">{{ group.label }}</p>
                        <p class="mt-0.5 text-[11px] text-stone-400">{{ group.description }}</p>
                        <p v-if="contextSaved[group.key]" class="mt-1 text-[10.5px] text-green-600">
                          {{ contextSaved[group.key] }}
                        </p>
                      </div>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <button
                          v-if="group.key !== 'memory'"
                          type="button"
                          @click="saveContextGroup(group.key)"
                          :disabled="contextSaving[group.key] || agentEditingId === null || !group.drafts.length"
                          class="h-7 px-2.5 rounded-lg bg-stone-800 text-[11.5px] text-white hover:bg-stone-700 disabled:opacity-40 transition"
                        >
                          {{ contextSaving[group.key] ? '保存中…' : '保存' }}
                        </button>
                        <button
                          v-if="group.key !== 'memory'"
                          type="button"
                          @click="contextPickerGroup = group.key"
                          class="h-7 px-2.5 rounded-lg border border-stone-200 bg-white text-[11.5px] text-stone-600 hover:bg-stone-50 transition"
                        >
                          + 添加
                        </button>
                        <button
                          v-else
                          type="button"
                          @click="addMemoryDraft"
                          :disabled="agentEditingId === null"
                          class="h-7 px-2.5 rounded-lg border border-stone-200 bg-white text-[11.5px] text-stone-600 hover:bg-stone-50 disabled:opacity-40 transition"
                        >
                          + 新增记忆
                        </button>
                      </div>
                    </div>

                    <div v-if="group.key === 'memory'">
                      <p v-if="!memoryDrafts.length" class="mt-2 py-3 text-center text-[11.5px] text-stone-400">
                        暂无记忆，点「+ 新增记忆」添加一条。
                      </p>
                      <div
                        v-for="memory in memoryDrafts"
                        :key="memory.id"
                        class="mt-2 flex items-center gap-2"
                      >
                        <input
                          type="text"
                          :value="memory.content"
                          @change="updateMemoryContent(memory, ($event.target as HTMLInputElement).value)"
                          maxlength="20000"
                          placeholder="例如：用户偏好中文回答，先看结论再看依据。"
                          class="h-8 min-w-0 max-w-xl flex-1 rounded-lg border border-stone-200 px-2.5 text-[12px]"
                        />
                        <button
                          type="button"
                          @click="removeMemoryDraft(memory)"
                          title="删除记忆"
                          class="h-8 w-8 shrink-0 rounded-lg text-stone-400 hover:bg-red-50 hover:text-red-600 transition"
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6" />
                          </svg>
                        </button>
                      </div>
                    </div>

                    <template v-else>
                    <p v-if="!group.drafts.length" class="mt-2 py-3 text-center text-[11.5px] text-stone-400">
                      暂无分段
                    </p>

                    <div
                      v-for="draft in group.drafts"
                      :key="draft.localId"
                      class="mt-2 rounded-lg border border-stone-200 bg-white p-3"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div class="min-w-0">
                          <p class="text-[12px] font-medium text-stone-700">
                            {{ draft.title || draft.key }}
                            <span class="ml-1.5 rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-normal text-stone-500">{{ draft.trustHint }}</span>
                          </p>
                          <p class="mt-0.5 text-[10.5px] leading-[1.5] text-stone-400">{{ presetDescription(draft) }}</p>
                        </div>
                        <div class="flex shrink-0 items-center gap-2">
                          <label class="flex items-center gap-1 text-[11px] text-stone-500">
                            <input v-model="draft.enabled" type="checkbox" class="h-3.5 w-3.5 accent-stone-800" />
                            启用
                          </label>
                          <button
                            v-if="draft.bindingId === null"
                            type="button"
                            @click="removeContextDraft(draft.localId)"
                            class="text-[11px] text-stone-400 hover:text-red-600"
                          >
                            移除
                          </button>
                        </div>
                      </div>

                      <div v-if="draft.resolver === 'agent_doc'" class="mt-2">
                        <div class="flex items-center justify-between gap-2">
                          <span class="text-[11px] text-stone-500">
                            内容{{ draft.globalDoc ? '（全局共享，修改会影响所有 Agent）' : '' }}
                          </span>
                          <button
                            v-if="draft.key in GENERATE_LABELS"
                            type="button"
                            :disabled="generatingContext === draft.localId"
                            @click="generateDraftContent(draft)"
                            class="h-7 px-2.5 shrink-0 rounded-lg border border-stone-200 bg-white text-[11px] text-stone-600 hover:bg-stone-50 disabled:opacity-50 transition"
                          >
                            {{ generatingContext === draft.localId ? '生成中…' : generateButtonLabel(draft.key) }}
                          </button>
                        </div>
                        <textarea
                          v-model="draft.content"
                          rows="4"
                          maxlength="20000"
                          :placeholder="presetDescription(draft)"
                          class="mt-1 w-full resize-y rounded-lg border border-stone-200 px-2.5 py-2 text-[12px] leading-[1.6]"
                        />
                        <p v-if="contextGenerateError && generatingContext === null" class="mt-1 text-[11px] text-red-600">
                          {{ contextGenerateError }}
                        </p>
                      </div>
                    </div>
                    </template>
                  </div>
                </div>

                <div class="rounded-xl border border-stone-200 p-3">
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="text-[12.5px] font-medium text-stone-700">上下文拼接顺序</p>
                      <p class="mt-0.5 text-[11.5px] text-stone-400">
                        拖动条目调整拼接顺序，越靠前越先注入；也可用右侧上下按钮微调。
                      </p>
                      <p class="mt-0.5 text-[11.5px] text-stone-400">
                        只有 Identity、Soul、Agents Guide 有权发出指令，其余只是数据。
                      </p>
                      <p v-if="orderSaved" class="mt-1 text-[10.5px] text-green-600">{{ orderSaved }}</p>
                      <p v-if="orderError" class="mt-1 text-[10.5px] text-red-600">{{ orderError }}</p>
                    </div>
                    <span class="shrink-0 text-[10.5px] text-stone-400">{{ contextDrafts.length }} 个分段</span>
                  </div>

                  <p v-if="agentEditingId === null" class="mt-3 text-[11px] text-stone-400">
                    新建 Agent 需先用底部「保存」创建后，才能调整拼接顺序。
                  </p>
                  <p v-else-if="!contextDrafts.length" class="mt-3 py-3 text-center text-[11.5px] text-stone-400">
                    暂无可排序的上下文分段。
                  </p>
                  <div v-else class="mt-3 space-y-1.5">
                    <div
                      v-for="(draft, index) in contextDrafts"
                      :key="draft.localId"
                      draggable="true"
                      @dragstart="onOrderDragStart($event, index)"
                      @dragover="onOrderDragOver($event, index)"
                      @drop="onOrderDrop($event, index)"
                      @dragend="onOrderDragEnd"
                      :class="[
                        orderDraggingId === draft.localId ? 'opacity-40' : '',
                        orderDropIndex === index && orderDraggingId !== null
                          ? 'border-stone-800 bg-stone-100'
                          : 'border-stone-200 bg-white',
                      ]"
                      class="flex items-center gap-2 rounded-lg border px-2.5 py-2 text-[12px]"
                    >
                      <span class="shrink-0 cursor-grab text-stone-400" title="拖动排序">
                        <svg width="12" height="16" viewBox="0 0 12 16" fill="currentColor">
                          <circle cx="3" cy="3" r="1" /><circle cx="9" cy="3" r="1" />
                          <circle cx="3" cy="8" r="1" /><circle cx="9" cy="8" r="1" />
                          <circle cx="3" cy="13" r="1" /><circle cx="9" cy="13" r="1" />
                        </svg>
                      </span>
                      <span class="w-5 shrink-0 text-[11px] text-stone-400">{{ index + 1 }}</span>
                      <span class="min-w-0 flex-1 truncate text-stone-700">{{ draft.title || draft.key }}</span>
                      <span class="shrink-0 text-[10.5px] text-stone-400">
                        {{ draft.key }} · {{ draft.trustHint }} · 优先级 {{ draft.priority }}{{ draft.enabled ? '' : ' · 未启用' }}
                      </span>
                      <button
                        type="button"
                        @click="moveContextDraft(index, index - 1)"
                        :disabled="index === 0"
                        class="h-6 w-6 shrink-0 rounded border border-stone-200 text-[11px] text-stone-500 hover:bg-stone-50 disabled:opacity-30"
                        title="上移"
                      >↑</button>
                      <button
                        type="button"
                        @click="moveContextDraft(index, index + 1)"
                        :disabled="index === contextDrafts.length - 1"
                        class="h-6 w-6 shrink-0 rounded border border-stone-200 text-[11px] text-stone-500 hover:bg-stone-50 disabled:opacity-30"
                        title="下移"
                      >↓</button>
                    </div>
                  </div>

                  <div class="mt-3 flex items-center justify-between gap-3">
                    <p v-if="orderDirty" class="text-[10.5px] text-amber-600">顺序已调整，记得保存。</p>
                    <span v-else />
                    <button
                      type="button"
                      @click="saveContextOrder"
                      :disabled="agentEditingId === null || orderSaving || !contextDrafts.length"
                      class="h-8 px-4 shrink-0 rounded-lg bg-stone-800 text-[12px] text-white hover:bg-stone-700 disabled:opacity-40 transition"
                    >
                      {{ orderSaving ? '保存中…' : '保存顺序' }}
                    </button>
                  </div>
                </div>

                <div v-if="adminPrompts.length" class="rounded-xl border border-stone-200 p-3">
                  <p class="text-[12.5px] font-medium text-stone-700">提示词版本</p>
                  <div class="mt-2 max-h-40 space-y-1 overflow-y-auto scroll-thin">
                    <div
                      v-for="p in adminPrompts"
                      :key="p.version"
                      class="flex items-center justify-between gap-2 rounded-lg bg-stone-50 px-2.5 py-1.5 text-[11.5px]"
                    >
                      <button
                        type="button"
                        @click="agPrompt = p.system_prompt; agPromptNote = p.note"
                        class="min-w-0 truncate text-left text-stone-600 hover:text-stone-900"
                        :title="p.system_prompt"
                      >
                        v{{ p.version }} · {{ p.note || '无备注' }}
                      </button>
                      <span v-if="p.version === adminAgents.find((a) => a.id === agentEditingId)?.active_prompt_version" class="shrink-0 text-[10.5px] text-green-600">生效中</span>
                      <button
                        v-else
                        type="button"
                        @click="activateVersion(p.version)"
                        class="shrink-0 text-[11px] text-stone-500 hover:text-stone-900"
                      >
                        启用
                      </button>
                    </div>
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

    <div
      v-if="contextPickerGroup"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 backdrop-blur-sm"
      @mousedown.self="contextPickerGroup = null"
    >
      <div class="w-[min(92vw,460px)] rounded-2xl bg-white p-5 shadow-xl shadow-stone-900/10">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h4 class="text-[15px] font-semibold text-stone-800">添加 {{ contextPickerLabel }}</h4>
            <p class="mt-0.5 text-[11.5px] leading-[1.5] text-stone-400">
              选好后会自动填好优先级、Token 预算和信任级别；你只需要填写内容（如果有）。
            </p>
          </div>
          <button
            type="button"
            @click="contextPickerGroup = null"
            class="h-7 w-7 rounded-lg text-stone-400 hover:bg-stone-100 hover:text-stone-700"
          >
            ×
          </button>
        </div>

        <div class="mt-4 space-y-2">
          <button
            v-for="preset in activePresets"
            :key="preset.key"
            type="button"
            :disabled="contextDrafts.some((d) => d.key === preset.key)"
            @click="addPresetContext(preset)"
            class="w-full rounded-xl border border-stone-200 px-3 py-2.5 text-left transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-[13px] font-medium text-stone-800">{{ preset.title }}</span>
              <span v-if="contextDrafts.some((d) => d.key === preset.key)" class="text-[10.5px] text-stone-400">已添加</span>
            </div>
            <p class="mt-1 text-[11.5px] leading-[1.5] text-stone-500">{{ preset.description }}</p>
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="saveToast"
      role="status"
      class="pointer-events-none fixed inset-0 z-[80] flex items-center justify-center"
    >
      <div class="rounded-full bg-stone-800 px-5 py-2.5 text-[12.5px] text-white shadow-xl">
        {{ saveToast }}
      </div>
    </div>
  </Teleport>
</template>
