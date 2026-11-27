<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChatMarkdown from './ChatMarkdown.vue'
import SiteIcon from './SiteIcon.vue'
import { useChat, type ChatMessage } from '../stores/chat'
import { useUi } from '../stores/ui'
import { useWorkspace } from '../stores/workspace'
import { useAuth } from '../stores/auth'
import { useModels } from '../stores/models'
import { useAgents } from '../stores/agents'
import type { AgentDto, ChatModelOption } from '../api/settings'
import { getContextUsage, type ContextUsageDto } from '../api/session'
import { formatDateTime, formatTokenCompact } from '../utils/format'
import { sourceHost, safeHttpUrl } from '../utils/url'

/* ---------------- 首页态热力图 Sessions / Credits（从 git 历史恢复） ---------------- */
const heatTab = ref<'sessions' | 'credits'>('sessions')

/** 确定性伪随机，保证每次渲染一致 */
function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const WEEKS = 48 // Dec 初 → Nov 末 大约 48 周可见区域
const DAYS = 7

/** 生成 [WEEKS][DAYS] 的 0–4 强度网格 */
function buildGrid(seed: number) {
  const rnd = mulberry32(seed)
  const grid: number[][] = []
  for (let w = 0; w < WEEKS; w++) {
    const col: number[] = []
    for (let d = 0; d < DAYS; d++) {
      // 制造一点「工作日更热」的分布，观感更真实
      const base = rnd()
      const weekdayBias = d === 0 || d === 6 ? -0.15 : 0.12
      const v = Math.max(0, Math.min(1, base + weekdayBias))
      const level = v < 0.22 ? 0 : v < 0.45 ? 1 : v < 0.68 ? 2 : v < 0.88 ? 3 : 4
      col.push(level)
    }
    grid.push(col)
  }
  return grid
}

const sessionsGrid = computed(() => buildGrid(20261124))
const creditsGrid = computed(() => buildGrid(19870921))
const activeGrid = computed(() =>
  heatTab.value === 'sessions' ? sessionsGrid.value : creditsGrid.value,
)

/** 强度对应的类（暖色五档，避免依赖动态 Tailwind 字符串） */
const levelClass: Record<number, string> = {
  0: 'bg-[#F1EBD9]',
  1: 'bg-[#DCE1BE]',
  2: 'bg-[#B3C58C]',
  3: 'bg-[#86A964]',
  4: 'bg-[#4F6B39]',
}

/** 月份标签：从 12 月起，共 12 个月 */
const monthLabels = ['12月', '1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月']
/** 每列属于哪一月：48 周 / 12 月 ≈ 每 4 周一个月份标签 */
const monthStartCols = monthLabels.map((_, i) => Math.floor((i * WEEKS) / 12))

/* ---------------- 输入框 ---------------- */
const draft = ref('')
const approveIdx = ref(0)
const approveOptions = ['自动批准', '每次询问', '只读']
const approveOpen = ref(false)
const approveRef = ref<HTMLElement | null>(null)

/* 思考档位：只有选中的模型支持深度思考时才展示（见下方 canThink） */
const autoIdx = ref(0)
const autoOptions = ['快速', '深度']
const autoOpen = ref(false)
const autoRef = ref<HTMLElement | null>(null)

/* ---------------- 模型选择 ---------------- */
/** 选中的模型行；列表到位后会自动落到管理员生效的那条，界面上显示的始终是具体模型名 */
const pickedModel = ref<ChatModelOption | null>(null)
const modelOpen = ref(false)
const modelRef = ref<HTMLElement | null>(null)
const {
  models: chatModels,
  usableModels,
  loaded: modelsLoaded,
  load: loadModels,
  clear: clearModels,
} = useModels()

/* ---------------- Agent 选择 ---------------- */
const agentOpen = ref(false)
const agentRef = ref<HTMLElement | null>(null)
const {
  agents: chatAgents,
  activeKey: pickedAgentKey,
  activeAgent,
  load: loadAgents,
  clear: clearAgents,
} = useAgents()

type AgentOption = Pick<AgentDto, 'agent_key' | 'name'>

function chooseAgent(agent: AgentOption) {
  pickedAgentKey.value = agent.agent_key
  agentOpen.value = false
}

function agentLabel(agent: AgentOption): string {
  return agent.name?.trim() || agent.agent_key
}

/** 该行能不能真的对话：available 缺省算可用（兼容旧后端响应） */
function isUsable(m: ChatModelOption): boolean {
  return m.available !== false
}

/** 下拉里只留模型名，去掉 «组织/» 前缀更好读 */
function shortName(model: string): string {
  return model.split('/').pop() || model
}

/** 下拉展示名：管理员在设置里给该行起了显示名称就用它，否则回退去前缀的模型名
 * （注意别叫 modelLabel：useChat() 已导出同名成员） */
function optionLabel(m: ChatModelOption): string {
  return m.name?.trim() || shortName(m.model)
}

// 模型列表到位（登录后首次拉取、管理员改配置后重拉）就把选中项落到具体某一行：
// 已选模型只要还在列表里就不动；列表变空视为刷新中间态，保留选择不动；
// 需回落时只在可用行里选（available=false 是构建了但聊不了）：优先 Xing4.0 → 生效行 → 首条可用
const DEFAULT_MODEL_KEYWORD = 'Xing4.0'
watch(chatModels, (list) => {
  // 刷新瞬间可能拿到空列表（保存设置时 clear→load 的中间态、或后端空响应）：
  // 保留已有选择，别把用户已选模型弄丢；真正的清空只在登出路径（watch(isLoggedIn)）做
  if (!list.length) return
  const current = pickedModel.value
  // 该模型仍在列表里就维持选择（即便 available 短暂抖动），避免下拉回退到默认值
  if (current && list.some((m) => m.platform === current.platform && m.model === current.model)) {
    return
  }
  const usable = list.filter(isUsable)
  if (!usable.length) {
    // 列表非空但全部构建失败（available=false），确实没有可聊的行，只能让用户重选
    pickedModel.value = null
    return
  }
  // 当前选择已从列表彻底消失（管理员删了/禁用该行）才回落：优先 Xing4.0 → 生效行 → 首条可用
  pickedModel.value =
    usable.find((m) => m.model.includes(DEFAULT_MODEL_KEYWORD)) ??
    usable.find((m) => m.is_active) ??
    usable[0]
})

function chooseModel(m: ChatModelOption) {
  if (!isUsable(m)) return // 构建失败的行不可选
  // 存整行引用而不是索引：管理员改配置后索引会错位
  pickedModel.value = m
  modelOpen.value = false
}

/** 当前 hover 展开 token 用量的消息序号；null 表示没有 */
const hoveredUsageIndex = ref<number | null>(null)
let usageCloseTimer: ReturnType<typeof setTimeout> | null = null

/** 鼠标进入图标：取消待关闭定时器并展开 */
function openUsage(i: number) {
  if (usageCloseTimer) {
    clearTimeout(usageCloseTimer)
    usageCloseTimer = null
  }
  hoveredUsageIndex.value = i
}

/** 鼠标离开图标/面板：延迟关闭，留时间让鼠标穿过两者之间的间隙 */
function closeUsage() {
  if (usageCloseTimer) clearTimeout(usageCloseTimer)
  usageCloseTimer = setTimeout(() => {
    hoveredUsageIndex.value = null
    usageCloseTimer = null
  }, 150)
}

const micOn = ref(false)

function toggleMic() {
  micOn.value = !micOn.value
}

/* ---------------- 对话（SSE 流式） ---------------- */
const {
  messages,
  busy,
  hasConversation,
  modelLabel,
  agentKey: activeAgentKey,
  promptVersion,
  startedAt,
  sessionId,
  send,
  stop,
} = useChat()
/* 新会话默认归入当前选中的工作区 */
const { activeId: workspaceId, activeWorkspace, loadSessions, sessions } = useWorkspace()
/* 问候语用登录用户名，未登录时退化为通用文案；isLoggedIn 也驱动模型列表的加载与作废 */
const { user, isLoggedIn } = useAuth()
/* 首页（品牌展示）/ 新对话画布 两态切换，由左上角 logo 与新对话入口驱动 */
const { view: stageView, goChat } = useUi()
const scroller = ref<HTMLElement | null>(null)

/** 跟随滚动：只在用户本来就贴在底部时才滚，避免打断回看上文 */
async function scrollToBottom(force = false) {
  await nextTick()
  const el = scroller.value
  if (!el) return
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
  if (force || nearBottom) el.scrollTop = el.scrollHeight
}

// 内容总长度变化即代有 delta 到达（含思考增量：思考刷得比正文快，不跟着滚会离开底部）
const streamedLength = computed(() =>
  messages.value.reduce((n, m) => n + m.content.length + m.reasoning.length, 0),
)
watch(streamedLength, () => void scrollToBottom())

/** 进入对话区（从首页切回 / 打开历史会话 / 首屏挂载）后，直接定位到最后一条消息 */
function jumpToLatest() {
  void scrollToBottom(true)
}
watch(stageView, (v) => {
  if (v !== 'home') jumpToLatest()
})
watch(sessionId, () => jumpToLatest())
onMounted(() => jumpToLatest())

/* ---------------- 上下文用量（右侧详情栏） ---------------- */
// 用 ref 存（普通 Map 不是响应式的，写入不会触发界面更新）；带上会话标记避免跨会话串数据
const usageEntry = ref<{ session: number; data: ContextUsageDto } | null>(null)
const contextLoading = ref(false)
const contextError = ref('')
let contextRequestSeq = 0

const contextUsage = computed(() =>
  sessionId.value != null && usageEntry.value?.session === sessionId.value
    ? usageEntry.value.data
    : null,
)

/** 拉取当前会话上下文用量；没有会话就不请求，模型窗口缺失时用默认值兜底 */
async function refreshContextUsage() {
  if (sessionId.value == null) return
  const seq = ++contextRequestSeq
  const session = sessionId.value
  const size = pickedModel.value?.context_size || 200000
  contextLoading.value = true
  try {
    const result = await getContextUsage(session, size)
    // 只接受最后一次请求的结果；跨会话的结果一律丢弃
    if (seq === contextRequestSeq && sessionId.value === session) {
      usageEntry.value = { session, data: result }
    }
  } catch (e) {
    // 网络抖动 / 接口失败：保留上次成功的结果，并暴露原因
    contextError.value = e instanceof Error ? e.message : '用量请求失败'
  } finally {
    if (seq === contextRequestSeq) contextLoading.value = false
  }
}

/** 会话切换、模型窗口变化、流式结束时刷新（不在每个 token 到达时请求） */
watch(
  [sessionId, pickedModel],
  () => void refreshContextUsage(),
  { immediate: true },
)
watch(busy, (v) => { if (!v) void refreshContextUsage() })

/** 当前选中的模型有没有深度档位（后端 /settings/models 的 supports_thinking） */
const canThink = computed(() => pickedModel.value?.supports_thinking === true)

/** 档位只两档：快速=显式关思考，深度=走该平台的 on 参数。
 * 模型不支持深度时一律按快速发，同时工具条上的档位选择也不显示 */
const thinking = computed(() => (canThink.value ? autoIdx.value === 1 : false))

/* 思考过程块的展开状态：只记用户手动点过的条目，
   其余按「还在流且还没出正文」自动展开，出正文后自动收起 */
const reasoningToggled = ref<Record<number, boolean>>({})
function isReasoningOpen(i: number, m: ChatMessage): boolean {
  const manual = reasoningToggled.value[i]
  return manual === undefined ? m.streaming && !m.content : manual
}
function toggleReasoning(i: number, m: ChatMessage) {
  reasoningToggled.value[i] = !isReasoningOpen(i, m)
  // 重新展开时恢复跟滚（max 滚到底不会误触发上翻判定，无需重置）
  if (isReasoningOpen(i, m)) reasoningFollow.value[i] = true
}

/* 思考面板自身是 max-h 滚动容器：外层 scroller 滚不到它内部，
   得在每条 reasoning 增量到达时把它自己滚到底；
   用户在面板里向上滚则暂停跟滚，尊重回看，重新贴底后恢复 */
const reasoningEls = new Map<number, HTMLElement>()
const reasoningFollow = ref<Record<number, boolean>>({})
const reasoningAnchor = new Map<number, number>()
// 模板 ref 回调还会收到组件实例，这里只关心原生元素
function setReasoningRef(i: number, el: unknown) {
  if (el instanceof HTMLElement) reasoningEls.set(i, el)
  else {
    reasoningEls.delete(i)
    reasoningAnchor.delete(i)
  }
}
function onReasoningScroll(i: number, e: Event) {
  const el = e.target as HTMLElement
  const prev = reasoningAnchor.get(i)
  reasoningAnchor.set(i, el.scrollTop)
  if (prev === undefined) return
  if (messages.value[i]?.streaming) {
    // 跟滚是“贴底”：内容增长时浏览器 auto 保留视口位置，表现为 scrollTop 被动变大；
    // 被动下滚或手动下滚到底恢复跟滚，向上滚（delta 为负）才是用户回看，暂停跟滚
    if (el.scrollTop > prev || el.scrollHeight - el.scrollTop - el.clientHeight < 40) {
      reasoningFollow.value[i] = true
    } else {
      reasoningFollow.value[i] = false
    }
    return
  }
  // 收尾后的滚动都算手动回看/回看后重新贴底
  reasoningFollow.value[i] = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}
// 监听 streamedLength（delta/reasoning 共用计数）:最后一条还在流的消息的思考增量一到就贴底,
// 面板收起时 scrollTop=0 会把内容顶出去,所以只在展开态处理
watch(streamedLength, () => {
  let i = -1
  for (let k = messages.value.length - 1; k >= 0; k--) {
    const m = messages.value[k]
    if (m.role === 'assistant' && m.streaming && m.reasoning) {
      i = k
      break
    }
  }
  if (i === -1 || !isReasoningOpen(i, messages.value[i]) || reasoningFollow.value[i] === false) return
  const el = reasoningEls.get(i)
  if (el) {
    el.scrollTop = el.scrollHeight
    reasoningAnchor.set(i, el.scrollTop)
  }
})

/* 已等待秒数：推理模型首字可能要一分多钟，干等「正在思考」容易被当成卡死 */
const now = ref(0)
let ticker: ReturnType<typeof setInterval> | undefined

const waited = computed(() =>
  startedAt.value ? Math.max(0, Math.floor((now.value - startedAt.value) / 1000)) : 0,
)

function clearTicker() {
  if (ticker !== undefined) {
    clearInterval(ticker)
    ticker = undefined
  }
}

watch(
  busy,
  (running) => {
    clearTicker()
    if (!running) return
    now.value = Date.now()
    ticker = setInterval(() => (now.value = Date.now()), 1000)
  },
  { immediate: true },
)

function submit() {
  const text = draft.value.trim()
  if (!text || busy.value) return
  draft.value = ''
  // 首页态直接打字发送：切回对话视图（此时 hasConversation 已为真，视图自动让位消息流）
  goChat()
  void send(text, {
    thinking: thinking.value,
    workspace_id: workspaceId.value,
    platform: pickedModel.value?.platform,
    model: pickedModel.value?.model,
    agent_key: pickedAgentKey.value,
  }).then(() =>
    // 本轮结束（含新建会话/首条消息生成标题）后刷新左侧栏会话列表
    loadSessions(),
  )
  void scrollToBottom(true)
}

/** 输入法合成期间（中文选字等）：Enter 是确认候选词，不能当发送键 */
const composing = ref(false)

function onCompositionEnd() {
  composing.value = false
}

function onKeydown(e: KeyboardEvent) {
  // isComposing 是标准标志；keyCode 229 兼容部分输入法/内核在合成期不发 isComposing 的情况
  if (composing.value || e.isComposing || e.keyCode === 229) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

/* ---------------- 右侧对话详情面板 ---------------- */
/** 详情栏折叠状态：默认折叠，左列占满，右栏收成窄轨 */
const detailCollapsed = ref(true)
/** 详情栏内容：chat=对话信息，sources=来源信息；入口不同显示不同内容 */
type DetailMode = 'chat' | 'sources'
const detailMode = ref<DetailMode>('chat')
/** 来源栏当前对应哪条消息；null 表示整段会话 */
const sourceMessageIndex = ref<number | null>(null)
/** 后端会给会话生成标题（首条消息摘要），列表刷新前用本轮提问兜底 */
const sessionTitle = ref('')
// sessions 刷新（loadSessions）后同步真实标题
watch(sessions, (list) => {
  const found = sessionId.value ? list.find((s) => s.id === sessionId.value) : undefined
  if (found?.title) sessionTitle.value = found.title
})
watch(sessionId, (v, old) => {
  if (v === old) return
  // 展开态是按消息下记的，换会话后下标会指向另一条消息，直接作废
  reasoningToggled.value = {}
  reasoningFollow.value = {}
  detailMode.value = 'chat'
  sourceMessageIndex.value = null
  if (!v) {
    sessionTitle.value = ''
    return
  }
  const found = sessions.value.find((s) => s.id === v)
  sessionTitle.value = found?.title || messages.value.find((m) => m.role === 'user')?.content.slice(0, 30) || ''
})

const usedTools = computed(() => [...new Set(messages.value.flatMap((m) => m.toolCalls.map((c) => c.name)))])
/** 右侧「参考来源」：汇总本会话所有引用，按正文编号去重排序 */
const allCitations = computed(() => {
  const seen = new Set<number>()
  const out: ChatMessage['citations'] = []
  for (const m of messages.value) {
    for (const c of m.citations) {
      if (seen.has(c.index)) continue
      seen.add(c.index)
      out.push(c)
    }
  }
  return out.sort((a, b) => a.index - b.index)
})
/** 来源栏显示的内容：跟随点开的那条消息；从右上角展开时才是整段会话 */
const activeCitations = computed(() =>
  sourceMessageIndex.value === null
    ? allCitations.value
    : (messages.value[sourceMessageIndex.value]?.citations ?? []),
)
/** 点正文里的 [n] 或「N篇来源」：来源栏已打开同一条消息则收起，否则展开该消息的来源 */
function toggleSources(messageIndex?: number) {
  if (
    !detailCollapsed.value
    && detailMode.value === 'sources'
    && sourceMessageIndex.value === (messageIndex ?? null)
  ) {
    detailCollapsed.value = true
    return
  }
  sourceMessageIndex.value = messageIndex ?? null
  detailCollapsed.value = false
  detailMode.value = 'sources'
}
/** 点正文 [n] 时沿用所在消息的来源列表 */
function citeFromMessage(messageIndex: number) {
  toggleSources(messageIndex)
}
/** 点右侧窄轨的展开按钮：只显示对话信息 */
function openChatDetails() {
  sourceMessageIndex.value = null
  detailCollapsed.value = false
  detailMode.value = 'chat'
  // 展开详情栏时补一次拉取，避免会话已在、watch 未触发导致一直显示「—」
  void refreshContextUsage()
}
const lastError = computed(() => [...messages.value].reverse().find((m) => m.error)?.error || '')
const lastActivity = computed(() => {
  const done = messages.value.filter((m) => m.role === 'assistant' && m.content)
  return done.length ? new Date().toLocaleTimeString('zh-CN', { hour12: false }) : ''
})

/** 按钮里最多展示 3 个不同站点的图标，同一域名只占一个位置 */
function buttonSources(citations: ChatMessage['citations']) {
  const seen = new Set<string>()
  return citations.filter((c) => {
    const domain = sourceHost(c.url)
    if (!domain || seen.has(domain)) return false
    seen.add(domain)
    return true
  }).slice(0, 3)
}

/** 模型偶尔会在正文末尾自己列「参考来源：[n]…」，与下方按钮重复；展示时去掉这一段 */
function displayContent(content: string): string {
  for (const label of ['参考来源', '采用的来源']) {
    const idx = content.lastIndexOf(label)
    if (idx < 0) continue
    const tail = content.slice(idx)
    // 尾部只剩标题 + [n] 编号（含流式未写完的半个编号）才当来源段裁掉，避免误伤正文
    if (new RegExp(`^${label}\\*{0,2}\\s*[：:][\\s\\[\\]\\d]*$`, 'u').test(tail)) {
      return content.slice(0, idx).replace(/\*+\s*$/, '').trimEnd()
    }
  }
  return content.trimEnd()
}

/** 我方消息的行内编辑与复制 */
const editingIndex = ref<number | null>(null)
const editDraft = ref('')
const copiedIndex = ref<number | null>(null)
/** 只有最后一条用户消息可编辑：更早的提问后面已有多轮对话，编辑它们等于改写历史 */
const lastUserIndex = computed(() => {
  for (let k = messages.value.length - 1; k >= 0; k--) {
    if (messages.value[k].role === 'user') return k
  }
  return -1
})
function startEdit(i: number, text: string) {
  if (busy.value || i !== lastUserIndex.value) return
  editingIndex.value = i
  editDraft.value = text
}
function cancelEdit() {
  editingIndex.value = null
}
function saveEdit() {
  const i = editingIndex.value
  const text = editDraft.value.trim()
  if (i === null || !text || busy.value) return
  editingIndex.value = null
  // 替换当前对话：本地截掉这条及其之后的消息，再带 regenerate 重新发送，后端同步删旧轮并重新生成
  messages.value.splice(i)
  void send(text, {
    thinking: thinking.value,
    workspace_id: workspaceId.value,
    platform: pickedModel.value?.platform,
    model: pickedModel.value?.model,
    agent_key: pickedAgentKey.value,
    regenerate: true,
  }).then(() => loadSessions())
  void scrollToBottom(true)
}
async function copyMsg(i: number, text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedIndex.value = i
    setTimeout(() => {
      if (copiedIndex.value === i) copiedIndex.value = null
    }, 1500)
  } catch {
    /* 裁剪板不可用时静默 */
  }
}

/** 点开模型下拉时补一次拉取：首次加载失败（登录态恢复晚 / 网络抖动）后，
 * store 里 loaded 仍为 false，用户点开下拉是唯一的重试入口 */
function toggleModelDropdown() {
  modelOpen.value = !modelOpen.value
  if (modelOpen.value && !modelsLoaded.value) void loadModels(true)
}

function closeDropdownsOnOutside(e: MouseEvent) {
  if (approveRef.value && !approveRef.value.contains(e.target as Node)) approveOpen.value = false
  if (autoRef.value && !autoRef.value.contains(e.target as Node)) autoOpen.value = false
  if (modelRef.value && !modelRef.value.contains(e.target as Node)) modelOpen.value = false
  if (agentRef.value && !agentRef.value.contains(e.target as Node)) agentOpen.value = false
}
onMounted(() => {
  document.addEventListener('mousedown', closeDropdownsOnOutside)
  // 模型与 agent 列表都要登录才能读：已登录（刷新页面后 restoreSession 完成）就直接拉一次
  if (isLoggedIn.value) {
    void loadModels()
    void loadAgents()
  }
})
// 登录后刷新可选配置，登出作废缓存与选中项，避免下一个账号看到上一个的列表
watch(isLoggedIn, (v) => {
  if (v) {
    void loadModels(true)
    void loadAgents(true)
  } else {
    clearModels()
    pickedModel.value = null
    clearAgents()
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', closeDropdownsOnOutside)
  if (usageCloseTimer) clearTimeout(usageCloseTimer)
  clearTicker()
})
</script>

<template>
  <section class="relative h-full flex bg-white overflow-hidden">
    <!-- 左侧主栏：对话态且详情栏未折叠时占 3/4（腾出右侧详情），其余态占满 -->
    <div class="min-w-0 flex flex-col" :class="hasConversation && !detailCollapsed ? 'w-3/4' : 'w-full'">
    <!-- 会话中：消息流滚动区（新对话态切到下方的 v-else 间隔） -->
    <div v-if="hasConversation" ref="scroller" class="flex-1 min-h-0 overflow-y-auto scroll-thin px-6 pt-12 pb-4">
      <div class="mx-auto max-w-[860px] flex flex-col items-center">
        <div class="w-full py-1">
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="mb-6 flex"
            :class="m.role === 'user' ? (editingIndex === i ? 'justify-center' : 'justify-end') : 'justify-start'"
          >
            <!-- 用户消息编辑态：复用底部输入框外观与工具栏 -->
            <div v-if="m.role === 'user' && editingIndex === i" class="w-full max-w-[720px]">
              <div
                class="rounded-3xl border border-stone-200 bg-white shadow-[0_6px_24px_rgba(0,0,0,0.06)] overflow-hidden"
              >
                <textarea
                  v-model="editDraft"
                  @keydown.esc="cancelEdit"
                  rows="2"
                  class="w-full resize-none bg-transparent px-5 pt-4 pb-1.5 text-[14px] leading-relaxed text-stone-800 outline-none"
                />
                <!-- 工具条：+ / 附件 | 语音 / 发送（发送即保存） -->
                <div class="flex items-center justify-between gap-2 px-3 pb-3 pt-1.5">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <button
                      type="button"
                      class="h-9 w-9 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 hover:text-stone-700 transition"
                      title="添加"
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="h-9 w-9 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 hover:text-stone-700 transition"
                      title="附件"
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                      </svg>
                    </button>
                  </div>
                  <div class="flex items-center gap-1.5">
                    <button
                      type="button"
                      class="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-stone-500 hover:bg-stone-100 transition"
                      title="取消编辑（Esc）"
                      @click="cancelEdit"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      @click="toggleMic"
                      class="h-9 w-9 grid place-items-center rounded-full transition"
                      :class="micOn ? 'bg-stone-800 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-700'"
                      :title="micOn ? '停止语音' : '语音输入'"
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="2" width="6" height="12" rx="3" />
                        <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      @click="saveEdit"
                      :disabled="!editDraft.trim()"
                      class="h-9 w-9 grid place-items-center rounded-full transition"
                      :class="editDraft.trim() ? 'bg-stone-900 text-white hover:bg-black' : 'bg-stone-100 text-stone-400 cursor-not-allowed'"
                      title="发送并重新生成"
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 19V5M5 12l7-7 7 7" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 用户消息（非编辑态）：气泡 + 下方时间/编辑/复制 -->
            <div v-else-if="m.role === 'user'" class="group flex max-w-[78%] flex-col items-end gap-1">
              <div
                class="rounded-2xl rounded-br-md bg-stone-100 px-4 py-2.5 text-[13.5px] leading-[1.7] text-stone-800 whitespace-pre-wrap break-words"
              >{{ m.content }}</div>

              <div class="flex items-center gap-1.5 px-1">
                <p class="text-[11px] text-stone-400 opacity-0 transition group-hover:opacity-100">{{ formatDateTime(m.created_at) }}</p>
                <div class="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                  <button
                    v-if="i === lastUserIndex"
                    type="button"
                    @click="startEdit(i, m.content)"
                    class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-stone-400 hover:bg-stone-100 hover:text-stone-600 transition"
                    title="编辑并重新生成（仅最后一条可编辑）"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                    </svg>
                    编辑
                  </button>
                  <button
                    type="button"
                    @click="copyMsg(i, m.content)"
                    class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-stone-400 hover:bg-stone-100 hover:text-stone-600 transition"
                    title="复制"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="11" height="11" rx="2" />
                      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
                    </svg>
                    {{ copiedIndex === i ? '已复制' : '复制' }}
                  </button>
                </div>
              </div>
            </div>

            <!-- 助手消息 -->
            <div v-else class="group w-full min-w-0">
              <!-- 分析过程：思考增量 + 工具调用状态；出正文后自动收起，可手动展开回看 -->
              <div v-if="m.reasoning || m.toolCalls.length" class="mb-2 overflow-hidden rounded-xl border border-stone-200/80 bg-stone-50/70">
                <button
                  type="button"
                  @click="toggleReasoning(i, m)"
                  class="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11.5px] text-stone-500 hover:text-stone-700 transition"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3a6 6 0 0 0-3.5 10.9c.4.3.6.7.6 1.1h5.8c0-.4.2-.8.6-1.1A6 6 0 0 0 12 3ZM9 18h6M10 21h4" />
                  </svg>
                  {{
                    m.streaming && !m.content
                      ? '分析中…'
                      : m.citations.length
                        ? '已完成分析，共参考' + m.citations.length + '篇资料'
                        : '已完成分析，相关操作已执行'
                  }}
                  <span v-if="m.reasoning" class="text-stone-400">· {{ m.reasoning.length }} 字</span>
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    class="ml-auto transition-transform"
                    :class="isReasoningOpen(i, m) ? 'rotate-180' : ''"
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-show="isReasoningOpen(i, m)"
                  :ref="(el) => setReasoningRef(i, el)"
                  @scroll="onReasoningScroll(i, $event)"
                  class="max-h-64 overflow-y-auto scroll-thin px-3 pb-2.5 text-[12px] leading-[1.7] text-stone-500"
                >
                  <p v-if="m.reasoning" class="whitespace-pre-wrap break-words">{{ m.reasoning }}</p>
                  <div v-if="m.toolCalls.length" class="mt-1 space-y-1.5">
                    <div v-for="tc in m.toolCalls" :key="tc.callId || tc.name">
                      <div class="flex items-center gap-2 text-[11.5px] text-stone-500">
                        <span
                          v-if="tc.state === 'running'"
                          class="h-3 w-3 shrink-0 animate-spin rounded-full border-[1.5px] border-stone-300 border-t-stone-600"
                        ></span>
                        <svg
                          v-else
                          width="13"
                          height="13"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          class="shrink-0 text-emerald-600"
                        >
                          <path d="M20 6 9 17l-5-5" />
                        </svg>
                        <span class="min-w-0 truncate">
                          {{ tc.state === 'running' ? '正在调用 ' + tc.name : tc.name + ' 调用完成' }}
                        </span>
                        <span v-if="tc.state === 'running'" class="dots"></span>
                      </div>
                      <div
                        v-if="tc.state === 'done' && tc.name === 'web_search' && tc.citations.length"
                        class="mt-1.5 flex flex-wrap gap-1.5 pl-5"
                      >
                        <template v-for="c in tc.citations" :key="c.index">
                          <a
                            v-if="safeHttpUrl(c.url)"
                            :href="c.url"
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            :title="c.url"
                            class="inline-flex max-w-[240px] items-center gap-1.5 rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[11px] text-stone-600 transition hover:border-stone-300 hover:text-stone-900"
                          >
                            <SiteIcon :url="c.url" :size="14" />
                            <span class="truncate">{{ c.title || sourceHost(c.url) || c.url }}</span>
                          </a>
                          <span
                            v-else
                            class="inline-flex max-w-[240px] items-center gap-1.5 rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[11px] text-stone-500"
                          >
                            <SiteIcon :url="c.url" :size="14" />
                            <span class="truncate">{{ c.title || c.url }}</span>
                          </span>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 正文：自定义排版 + [n] 引用徽标 + 代码块复制 -->
              <ChatMarkdown
                v-if="displayContent(m.content)"
                :content="displayContent(m.content)"
                :final="!m.streaming"
                class="px-1 py-0.5"
                @cite="citeFromMessage(i)"
              />
              <div v-else-if="!m.streaming && !m.error" class="px-1 py-0.5 text-[13.5px] text-stone-400">（无内容）</div>

              <p v-if="m.error" class="mt-2 text-[12.5px] text-red-500">{{ m.error }}</p>
              <p v-else-if="m.streaming && !m.content && !m.reasoning" class="mt-2 text-[12.5px] text-stone-400">
                正在思考<span v-if="waited >= 3">，已等待 {{ waited }}s</span
                ><span v-if="waited >= 20">{{
                  m.thinking ? '（深度思考模式首字较慢，仍在生成）' : '（本轮是快速档，慢在上游排队）'
                }}</span><span class="dots"></span>
              </p>
              <!-- 参考来源：放在时间戳上方，点击到右侧详情栏展开完整列表 -->
              <div v-if="m.citations.length" class="mt-2 px-1">
                <button
                  type="button"
                  @click="toggleSources(i)"
                  class="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11.5px] text-stone-600 transition hover:bg-stone-100 hover:text-stone-800"
                  :title="!detailCollapsed && detailMode === 'sources' ? '收起右侧来源栏' : '在右侧展开来源'"
                >
                  <span class="flex -space-x-1.5">
                    <SiteIcon
                      v-for="c in buttonSources(m.citations)"
                      :key="c.index"
                      :url="c.url"
                      :size="16"
                      class="border border-white"
                    />
                  </span>
                  {{ m.citations.length }}篇来源
                  <span v-if="m.streaming" class="text-stone-400">仍在检索…</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>
              </div>

              <!-- token 用量：收起显示总数，展开详情浮在上方覆盖，不占布局高度 -->
              <div
                v-if="m.turnUsage && m.role === 'assistant'"
                class="relative mt-1.5 px-1"
                @mouseenter="openUsage(i)"
                @mouseleave="closeUsage()"
              >
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[10.5px] text-stone-400 hover:bg-stone-100 hover:text-stone-600 transition"
                  title="本轮 token 用量"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  {{ m.turnUsage.total_tokens.toLocaleString() }} tokens
                </button>
                <div
                  v-if="hoveredUsageIndex === i"
                  class="absolute bottom-full left-1 z-20 mb-1.5 inline-grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg border border-stone-200 bg-white px-3 py-2 text-[11px] shadow-lg"
                >
                  <span class="text-stone-400">输入</span>
                  <span class="text-right text-stone-700">{{ m.turnUsage.input_tokens.toLocaleString() }}</span>
                  <span class="text-stone-400">输出</span>
                  <span class="text-right text-stone-700">{{ m.turnUsage.output_tokens.toLocaleString() }}</span>
                  <span class="text-stone-400">合计</span>
                  <span class="text-right font-medium text-stone-800">{{ m.turnUsage.total_tokens.toLocaleString() }}</span>
                  <span class="text-stone-400">模型调用</span>
                  <span class="text-right text-stone-700">{{ m.turnUsage.model_calls }} 次</span>
                  <template v-if="m.turnUsage.input_token_details?.cache_read">
                    <span class="text-stone-400">缓存命中</span>
                    <span class="text-right text-emerald-600">{{ m.turnUsage.input_token_details.cache_read.toLocaleString() }}</span>
                  </template>
                  <template v-if="m.turnUsage.output_token_details?.reasoning">
                    <span class="text-stone-400">推理</span>
                    <span class="text-right text-stone-700">{{ m.turnUsage.output_token_details.reasoning.toLocaleString() }}</span>
                  </template>
                </div>
              </div>

              <p v-if="(m.content || m.error) && m.created_at" class="mt-1.5 px-1 text-[11px] text-stone-400 opacity-0 transition group-hover:opacity-100">{{ formatDateTime(m.created_at) }}</p>

            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 首页态：品牌插画 + slogan + 热力图（点左上角 logo 进入）；safe_center 兼顾高屏居中与窄屏不裁顶 -->
    <div v-else-if="stageView === 'home'" class="flex-1 min-h-0 overflow-y-auto scroll-thin px-6 pt-12 pb-4">
      <div class="mx-auto max-w-[860px] min-h-full flex flex-col items-center [justify-content:safe_center]">
        <!-- 品牌插画 -->
        <div class="relative">
          <svg width="104" height="104" viewBox="0 0 96 96" aria-hidden="true">
            <defs>
              <linearGradient id="brand-bg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#F3DFA8" />
                <stop offset="55%" stop-color="#D9C48A" />
                <stop offset="100%" stop-color="#8FAE77" />
              </linearGradient>
              <linearGradient id="brand-plane" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#3E3A33" />
                <stop offset="100%" stop-color="#5a5446" />
              </linearGradient>
            </defs>
            <!-- 柔光晕 -->
            <circle cx="48" cy="50" r="30" fill="url(#brand-bg)" opacity="0.35" />
            <!-- 主体圆 -->
            <circle cx="48" cy="50" r="22" fill="url(#brand-bg)" />
            <!-- 纸飞机 -->
            <path
              d="M32 58 L62 42 L46 62 L44 55 Z"
              fill="url(#brand-plane)"
              stroke="#2b2a22"
              stroke-width="0.6"
              stroke-linejoin="round"
            />
            <!-- 环绕轨道 -->
            <ellipse cx="48" cy="50" rx="34" ry="12" stroke="#B79B62" stroke-width="0.8" opacity="0.5" fill="none" transform="rotate(-18 48 50)" />
            <!-- 装饰星点 -->
            <circle cx="18" cy="24" r="2" fill="#C4A86A" />
            <circle cx="78" cy="30" r="1.6" fill="#7C9A5C" />
            <circle cx="82" cy="70" r="2" fill="#B79B62" />
            <circle cx="14" cy="72" r="1.4" fill="#8FAE77" />
          </svg>
        </div>

        <!-- 标题 -->
        <h1 class="mt-6 text-[30px] leading-tight font-medium tracking-tight text-[#2b2a22]">
          想到，即做到
        </h1>

        <!-- 热力图卡片 -->
        <div
          class="mt-8 w-full rounded-2xl border border-[#EDE7D2] bg-white p-5 shadow-[0_1px_3px_rgba(90,80,60,0.04)]"
        >
          <!-- 卡片头 -->
          <div class="flex items-center justify-between gap-3">
            <div class="inline-flex gap-1 p-0.5 rounded-full bg-[#F5F1E3] border border-[#EDE7D2]">
              <button
                type="button"
                @click="heatTab = 'sessions'"
                class="px-3 py-1 rounded-full text-[11px] font-medium transition"
                :class="
                  heatTab === 'sessions'
                    ? 'bg-white text-[#2b2a22] shadow-sm'
                    : 'text-[#7a7561] hover:text-[#2b2a22]'
                "
              >
                会话
              </button>
              <button
                type="button"
                @click="heatTab = 'credits'"
                class="px-3 py-1 rounded-full text-[11px] font-medium transition"
                :class="
                  heatTab === 'credits'
                    ? 'bg-white text-[#2b2a22] shadow-sm'
                    : 'text-[#7a7561] hover:text-[#2b2a22]'
                "
              >
                额度
              </button>
            </div>

            <div class="text-[10.5px] text-[#8a8872] tracking-wide">2025年12月 – 2026年11月</div>
          </div>

          <!-- 点阵网格 -->
          <div class="mt-4 overflow-x-auto scroll-thin">
            <div class="min-w-[560px]">
              <!-- 月份标签行 -->
              <div class="relative h-4 mb-1 text-[10px] text-[#a4a190]">
                <span
                  v-for="(m, i) in monthLabels"
                  :key="m"
                  class="absolute top-0"
                  :style="{ left: `${(monthStartCols[i] / WEEKS) * 100}%` }"
                >
                  {{ m }}
                </span>
              </div>

              <!-- 点阵：每列一周（7 天） -->
              <div class="flex gap-[3px]">
                <div
                  v-for="(col, w) in activeGrid"
                  :key="w"
                  class="flex flex-col gap-[3px]"
                >
                  <span
                    v-for="(lvl, d) in col"
                    :key="d"
                    class="w-[10px] h-[10px] rounded-[3px] transition-colors"
                    :class="levelClass[lvl]"
                    :title="`${heatTab === 'sessions' ? 'Session' : 'Credit'} intensity: ${lvl}`"
                  />
                </div>
              </div>

              <!-- 图例 -->
              <div class="mt-3 flex items-center justify-end gap-1.5 text-[10px] text-[#a4a190]">
                <span class="mr-1">少</span>
                <span v-for="l in [0, 1, 2, 3, 4]" :key="l" class="w-[10px] h-[10px] rounded-[3px]" :class="levelClass[l]" />
                <span class="ml-1">多</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 新对话：ChatGPT 式空白画布，问候语贴着输入框上方，整体靠上下两个间隔顶到视觉中部 -->
    <div v-else class="flex-[5] min-h-0 flex flex-col items-center justify-end px-6 pb-7">
      <h1 class="text-[22px] leading-tight font-medium tracking-tight text-stone-800">
        {{ (user?.nickname || user?.username) ? `${user.nickname || user.username}，想聊点什么？` : '想聊点什么？' }}
      </h1>
    </div>

    <!-- 输入框：会话中贴底；新对话时位于两间隔之间 -->
    <div class="shrink-0 px-6" :class="hasConversation ? 'pb-7' : stageView === 'home' ? 'pb-5' : ''">
      <div class="mx-auto max-w-[860px]">
        <div
          class="rounded-3xl border border-stone-200 bg-white shadow-[0_6px_24px_rgba(0,0,0,0.06)] overflow-hidden"
        >
          <!-- 上行：文本输入 -->
          <textarea
            v-model="draft"
            @keydown="onKeydown"
            @compositionstart="composing = true"
            @compositionend="onCompositionEnd"
            rows="2"
            :placeholder="busy ? '正在回答中，可以先输入下一条…' : '随便问点什么，或描述你想构建的东西…'"
            class="w-full resize-none bg-transparent px-5 pt-4 pb-1.5 text-[14px] leading-relaxed text-stone-800 placeholder:text-stone-400 outline-none"
          />

          <!-- 下行：工具条 -->
          <div class="flex items-center justify-between gap-2 px-3 pb-3 pt-1.5">
            <!-- 左侧：+ / 附件 / Auto approve -->
            <div class="flex items-center gap-1.5 min-w-0">
              <button
                type="button"
                class="h-9 w-9 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 hover:text-stone-700 transition"
                title="添加"
              >
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
              <button
                type="button"
                class="h-9 w-9 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-100 hover:text-stone-700 transition"
                title="附件"
              >
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>

              <div ref="approveRef" class="relative">
                <button
                  type="button"
                  @click="approveOpen = !approveOpen"
                  class="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-stone-600 hover:bg-stone-100 transition"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70">
                    <path d="M9 12l2 2 4-4" />
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                  {{ approveOptions[approveIdx] }}
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-stone-400" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="approveOpen"
                  class="absolute left-0 bottom-10 z-30 w-48 rounded-xl bg-white border border-stone-200 shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="(o, i) in approveOptions"
                    :key="o"
                    type="button"
                    @click="((approveIdx = i), (approveOpen = false))"
                    class="w-full text-left px-3 py-2 rounded-lg text-[12.5px] transition"
                    :class="
                      i === approveIdx
                        ? 'bg-stone-100 text-stone-900 font-medium'
                        : 'text-stone-600 hover:bg-stone-100'
                    "
                  >
                    {{ o }}
                  </button>
                </div>
              </div>
            </div>

            <!-- 右侧：Agent / 模型 / Auto / 麦克风 / 发送 -->
            <div class="flex items-center gap-1.5">
              <!-- Agent：默认 chat，管理员新增后立刻可选 -->
              <div ref="agentRef" class="relative">
                <button
                  type="button"
                  @click="agentOpen = !agentOpen"
                  class="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-stone-600 hover:bg-stone-100 transition"
                  title="选择 Agent"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="4" y="8" width="16" height="12" rx="2" />
                    <path d="M12 8V4M8 14h.01M16 14h.01M9 18h6" />
                  </svg>
                  {{ activeAgent ? agentLabel(activeAgent) : (pickedAgentKey || '默认 Agent') }}
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-stone-400" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="agentOpen"
                  class="absolute right-0 bottom-10 z-30 w-56 max-h-72 overflow-y-auto scroll-thin rounded-xl bg-white border border-stone-200 shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="a in chatAgents"
                    :key="a.id"
                    type="button"
                    @click="chooseAgent(a)"
                    class="w-full text-left px-3 py-2 rounded-lg text-[12.5px] transition"
                    :class="pickedAgentKey === a.agent_key ? 'bg-stone-100 text-stone-900 font-medium' : 'text-stone-600 hover:bg-stone-100'"
                  >
                    <span class="block truncate">{{ agentLabel(a) }}</span>
                    <span class="block truncate text-[11px] text-stone-400">{{ a.agent_key }} · v{{ a.active_prompt_version }}</span>
                  </button>
                  <p v-if="!chatAgents.length" class="px-3 py-2 text-[12px] text-stone-400">
                    管理员还没配置 Agent，发送时走默认 chat
                  </p>
                </div>
              </div>

              <!-- 模型：只列管理员接入的（不含密钥），平铺不标平台 -->
              <div ref="modelRef" class="relative">
                <button
                  type="button"
                  @click="toggleModelDropdown"
                  class="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-stone-600 hover:bg-stone-100 transition"
                  title="选择模型"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70" stroke-linejoin="round">
                    <path d="M12 2.6 21 7.3v9.4L12 21.4 3 16.7V7.3z" />
                    <path d="M3 7.3 12 12l9-4.7M12 12v9.4" />
                  </svg>
                  {{ pickedModel ? optionLabel(pickedModel) : '选择模型' }}
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-stone-400" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="modelOpen"
                  class="absolute left-1/2 -translate-x-1/2 bottom-10 z-30 w-fit min-w-36 max-w-72 max-h-72 overflow-y-auto scroll-thin rounded-xl bg-white border border-stone-200 shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="m in chatModels"
                    :key="m.platform + '/' + m.model"
                    type="button"
                    :disabled="!isUsable(m)"
                    @click="chooseModel(m)"
                    class="w-full text-left px-3 py-2 rounded-lg text-[12.5px] transition flex items-center gap-1.5"
                    :class="
                      !isUsable(m)
                        ? 'text-stone-300 cursor-not-allowed'
                        : pickedModel?.platform === m.platform && pickedModel?.model === m.model
                          ? 'bg-stone-100 text-stone-900 font-medium'
                          : 'text-stone-600 hover:bg-stone-100'
                    "
                    :title="isUsable(m) ? '' : m.unavailable_reason || '该模型构建失败，请联系管理员'"
                  >
                    <span class="min-w-0 truncate">{{ optionLabel(m) }}</span>
                    <span
                      v-if="formatTokenCompact(m.context_size)"
                      class="shrink-0 rounded bg-stone-100 px-1.5 py-0.5 text-[10px] text-stone-500"
                    >
                      {{ formatTokenCompact(m.context_size) }}
                    </span>
                    <span v-if="!isUsable(m)" class="shrink-0 text-[10.5px]">不可用</span>
                  </button>
                  <p v-if="!chatModels.length" class="px-3 py-2 text-[12px] text-stone-400">
                    管理员还没接入模型，发送时按后端生效配置走
                  </p>
                  <p v-else-if="!usableModels.length" class="px-3 py-2 text-[12px] text-amber-600">
                    接入的模型全部构建失败，请联系管理员检查密钥与端点
                  </p>
                </div>
              </div>

              <div v-if="canThink" ref="autoRef" class="relative">
                <button
                  type="button"
                  @click="autoOpen = !autoOpen"
                  class="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg text-[12px] text-stone-600 hover:bg-stone-100 transition"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70">
                    <path d="M12 2v4M12 18v4M4.9 4.9l2.9 2.9M16.2 16.2l2.9 2.9M2 12h4M18 12h4M4.9 19.1l2.9-2.9M16.2 7.8l2.9-2.9" />
                  </svg>
                  {{ autoOptions[autoIdx] }}
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-stone-400" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="autoOpen"
                  class="absolute right-0 bottom-10 z-30 w-36 rounded-xl bg-white border border-stone-200 shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="(o, i) in autoOptions"
                    :key="o"
                    type="button"
                    @click="((autoIdx = i), (autoOpen = false))"
                    class="w-full text-left px-3 py-2 rounded-lg text-[12.5px] transition"
                    :class="
                      i === autoIdx
                        ? 'bg-stone-100 text-stone-900 font-medium'
                        : 'text-stone-600 hover:bg-stone-100'
                    "
                  >
                    {{ o }}
                  </button>
                </div>
              </div>

              <button
                type="button"
                @click="toggleMic"
                class="h-9 w-9 grid place-items-center rounded-full transition"
                :class="
                  micOn
                    ? 'bg-stone-800 text-white'
                    : 'text-stone-500 hover:bg-stone-100 hover:text-stone-700'
                "
                :title="micOn ? '停止语音' : '语音输入'"
              >
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="2" width="6" height="12" rx="3" />
                  <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
                </svg>
              </button>

              <!-- 流式进行中变成「停止」，完成后恢复发送 -->
              <button
                type="button"
                @click="busy ? stop() : submit()"
                :disabled="!busy && !draft.trim()"
                class="h-9 w-9 grid place-items-center rounded-full transition"
                :class="
                  busy
                    ? 'bg-black text-white hover:bg-black/85'
                    : draft.trim()
                      ? 'bg-stone-900 text-white hover:bg-black'
                      : 'bg-stone-100 text-stone-400 cursor-not-allowed'
                "
                :title="busy ? '停止生成' : '发送'"
              >
                <svg v-if="busy" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="5" y="5" width="14" height="14" rx="2.5" />
                </svg>
                <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- 输入框下方提示 -->
        <p class="mt-3 text-center text-[12px] text-stone-400">
          {{
            busy
              ? '生成中… 点右侧黑色方块可中断'
              : activeWorkspace
                ? `新对话将归入「${activeWorkspace.name}」`
                : '选择工作区 (可选)'
          }}
        </p>
      </div>
    </div>

    <!-- 新对话态的下间隔（首页态由内容区自己占满）：略小于上间隔，输入框落在视觉中心稍偏上 -->
    <div v-if="!hasConversation && stageView !== 'home'" class="flex-[4] min-h-0" />
    </div><!-- /左侧主栏 -->

    <!-- 右侧 1/4 对话详情栏（仅会话中显示） -->
    <aside
      v-if="hasConversation"
      class="shrink-0 flex flex-col border-l border-stone-200 bg-stone-50/60 transition-[width] duration-300 ease-out"
      :class="detailCollapsed ? 'w-11 py-4 items-center' : detailMode === 'sources' ? 'w-1/4 overflow-y-auto scroll-thin px-5 py-3' : 'w-1/4 overflow-y-auto scroll-thin px-5 py-6'"
    >
      <!-- 折叠态：仅一个展开按钮的窄轨 -->
      <button
        v-if="detailCollapsed"
        type="button"
        @click="openChatDetails"
        class="h-8 w-8 shrink-0 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-200/70 hover:text-stone-700 transition"
        title="展开对话详情"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
      </button>

      <!-- 展开态 -->
      <template v-else>
        <div v-if="detailMode === 'chat'" class="flex items-center justify-between">
          <h2 class="text-[11px] font-medium tracking-[0.12em] uppercase text-stone-400">对话详情</h2>
          <button
            type="button"
            @click="detailCollapsed = true"
            class="h-7 w-7 grid place-items-center rounded-lg text-stone-400 hover:bg-stone-200/70 hover:text-stone-600 transition"
            title="折叠对话详情"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
          </button>
        </div>
      <div v-if="detailMode === 'chat'" class="mt-5 space-y-5">
        <div>
          <p class="text-[10.5px] text-stone-400 mb-1">标题</p>
          <p class="text-[13px] font-medium text-stone-800 leading-snug break-words">
            {{ sessionTitle || '未命名对话' }}
          </p>
        </div>
        <div>
          <p class="text-[10.5px] text-stone-400 mb-1">模型</p>
          <p class="text-[12.5px] text-stone-700 break-words">{{ modelLabel || '—' }}</p>
        </div>
        <div>
          <p class="text-[10.5px] text-stone-400 mb-1">Agent</p>
          <p class="text-[12.5px] text-stone-700 break-words">
            {{ activeAgentKey || '默认 chat' }}
            <span v-if="promptVersion" class="text-stone-400">· 提示词 v{{ promptVersion }}</span>
          </p>
        </div>
        <div>
          <p class="text-[10.5px] text-stone-400 mb-1">工作区</p>
          <p class="text-[12.5px] text-stone-700">{{ activeWorkspace?.name || '未分组' }}</p>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <p class="text-[10.5px] text-stone-400 mb-1">会话 ID</p>
            <p class="text-[12.5px] text-stone-700">{{ sessionId ?? '—' }}</p>
          </div>
          <div>
            <p class="text-[10.5px] text-stone-400 mb-1">消息数</p>
            <p class="text-[12.5px] text-stone-700">{{ messages.length }}</p>
          </div>
        </div>
        <div>
          <div class="flex items-baseline justify-between mb-1.5">
            <p class="text-[10.5px] text-stone-400">上下文用量</p>
            <span class="text-[10.5px] text-stone-400">{{ contextLoading ? '计算中…' : '' }}</span>
          </div>
          <template v-if="contextUsage">
            <div class="h-1.5 w-full overflow-hidden rounded-full bg-stone-200/80">
              <div
                class="h-full rounded-full transition-[width] duration-300"
                :class="contextUsage.usage_ratio > 0.9 ? 'bg-red-400' : contextUsage.usage_ratio > 0.7 ? 'bg-amber-400' : 'bg-emerald-500'"
                :style="{ width: `${Math.max(1, contextUsage.usage_ratio * 100)}%` }"
              />
            </div>
            <div class="mt-1.5 flex items-baseline justify-between gap-2">
              <p class="text-[12px] text-stone-700">
                剩余 <span class="font-medium">{{ formatTokenCompact(contextUsage.remaining_tokens) }}</span>
              </p>
              <p class="text-[10px] text-stone-400">
                {{ formatTokenCompact(contextUsage.used_tokens) }} / {{ formatTokenCompact(contextUsage.context_size) }}
                <span v-if="contextUsage.source === 'api'" title="来自模型 API 返回的真实 token 用量">· 实测</span>
                <span v-else title="由 tiktoken 估算，模型 API 尚未返回用量">· 估算</span>
              </p>
            </div>
            <p v-if="contextUsage.summary_chars" class="mt-1 text-[10px] text-stone-400">
              已压缩历史 · 摘要 {{ contextUsage.summary_chars }} 字
            </p>
          </template>
          <p v-else class="text-[11.5px] text-stone-400">—</p>
        </div>
        <div v-if="usedTools.length">
          <p class="text-[10.5px] text-stone-400 mb-1.5">使用过的工具</p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="t in usedTools"
              :key="t"
              class="inline-flex items-center rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[11px] text-stone-600"
            >
              {{ t }}
            </span>
          </div>
        </div>
        <div v-if="lastActivity">
          <p class="text-[10.5px] text-stone-400 mb-1">最近回答</p>
          <p class="text-[12.5px] text-stone-700">{{ lastActivity }}</p>
        </div>
        <div v-if="lastError">
          <p class="text-[10.5px] text-stone-400 mb-1">最近错误</p>
          <p class="text-[11.5px] leading-relaxed break-words text-red-500">{{ lastError }}</p>
        </div>
      </div>

      <!-- 来源模式：只显示来源列表，不带对话信息 -->
      <div v-else>
        <div class="mb-2 flex items-center gap-2">
          <p class="text-[13px] font-semibold text-stone-700">参考来源</p>
          <span class="rounded-full bg-stone-200/70 px-2 text-[11px] leading-5 text-stone-500">{{ activeCitations.length }}</span>
          <button
            type="button"
            @click="detailCollapsed = true"
            class="ml-auto h-7 w-7 grid place-items-center rounded-lg text-stone-400 hover:bg-stone-200/70 hover:text-stone-600 transition"
            title="折叠来源列表"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
          </button>
        </div>
        <ul v-if="activeCitations.length" class="max-h-[calc(100vh-6rem)] space-y-2.5 overflow-y-auto scroll-thin pr-1">
          <li v-for="c in activeCitations" :key="c.index">
            <a
              v-if="safeHttpUrl(c.url)"
              :href="c.url"
              target="_blank"
              rel="noopener noreferrer nofollow"
              :title="c.url"
              class="block rounded-xl border border-stone-200/80 bg-white p-3 transition hover:border-stone-300 hover:shadow-sm"
            >
              <span class="flex items-start gap-2.5">
                <SiteIcon :url="c.url" :size="20" class="mt-0.5 ring-1 ring-stone-200" />
                <span class="min-w-0 flex-1">
                  <span class="flex items-start justify-between gap-2">
                    <span class="line-clamp-2 text-[12.5px] font-medium leading-[1.5] text-stone-800">
                      {{ c.title || sourceHost(c.url) || c.url }}
                    </span>
                    <span class="shrink-0 rounded-md bg-stone-100 px-1.5 text-[10px] leading-5 text-stone-500">{{ c.index }}</span>
                  </span>
                  <span v-if="c.snippet" class="mt-1.5 block line-clamp-2 text-[11px] leading-[1.6] text-stone-500">{{ c.snippet }}</span>
                  <span class="mt-1.5 flex items-center gap-1.5 text-[10.5px] text-stone-400">
                    <span class="min-w-0 truncate">{{ sourceHost(c.url) }}</span>
                    <span v-if="c.published_date" class="shrink-0">· {{ c.published_date }}</span>
                    <span v-if="c.kind === 'page'" class="ml-auto shrink-0 rounded bg-emerald-50 px-1 text-emerald-600">已读</span>
                  </span>
                </span>
              </span>
            </a>
            <span v-else class="block rounded-xl border border-stone-200/80 bg-white p-3 text-[11.5px] text-stone-500">
              {{ c.index }}. {{ c.title || c.url }}
            </span>
          </li>
        </ul>
        <div v-else class="rounded-xl border border-dashed border-stone-200 px-3 py-8 text-center text-[12px] text-stone-400">
          本轮还没有参考来源
        </div>
      </div>
      </template>
    </aside>

    <!-- 右下角深色 ? 帮助按钮 -->
    <button
      type="button"
      class="absolute bottom-5 right-5 h-9 w-9 rounded-full bg-stone-900 text-white hidden lg:grid place-items-center shadow-[0_6px_18px_rgba(0,0,0,0.15)] hover:bg-black transition text-[12px] font-semibold"
      title="帮助"
    >
      ?
    </button>
  </section>
</template>

<style scoped>
/* 等待提示后的省略号呼吸（只动 opacity，兼容性无风险） */
.dots::after {
  content: '…';
  animation: dots-breathe 1.4s ease-in-out infinite;
}

@keyframes dots-breathe {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}
</style>
