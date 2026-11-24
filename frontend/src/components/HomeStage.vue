<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MarkdownRender from 'markstream-vue'
import 'markstream-vue/index.css'
import { useChat, type ChatMessage } from '../stores/chat'
import { useUi } from '../stores/ui'
import { useWorkspace } from '../stores/workspace'
import { useAuth } from '../stores/auth'
import { useModels } from '../stores/models'
import type { ChatModelOption } from '../api/settings'

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
const { models: chatModels, usableModels, load: loadModels, clear: clearModels } = useModels()

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

const micOn = ref(false)

function toggleMic() {
  micOn.value = !micOn.value
}

/* ---------------- 对话（SSE 流式） ---------------- */
const { messages, busy, hasConversation, modelLabel, startedAt, sessionId, send, stop } = useChat()
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
  }).then(() =>
    // 本轮结束（含新建会话/首条消息生成标题）后刷新左侧栏会话列表
    loadSessions(),
  )
  void scrollToBottom(true)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

/* ---------------- 右侧对话详情面板 ---------------- */
/** 详情栏折叠状态：默认折叠，左列占满，右栏收成窄轨 */
const detailCollapsed = ref(true)
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
  if (!v) {
    sessionTitle.value = ''
    return
  }
  const found = sessions.value.find((s) => s.id === v)
  sessionTitle.value = found?.title || messages.value.find((m) => m.role === 'user')?.content.slice(0, 30) || ''
})

const usedTools = computed(() => [...new Set(messages.value.flatMap((m) => m.tools))])
const lastError = computed(() => [...messages.value].reverse().find((m) => m.error)?.error || '')
const lastActivity = computed(() => {
  const done = messages.value.filter((m) => m.role === 'assistant' && m.content)
  return done.length ? new Date().toLocaleTimeString('zh-CN', { hour12: false }) : ''
})

/** 消息气泡下方的时间：悬停消息时才显现，完整到秒（年-月-日 时:分:秒） */
function formatMsgTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 引用卡片上的域名：后端给的 title 可能来自路径拼接，单独一行网址更好识别 */
function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** 只放行 http(s)：url 是外部搜索接口返的，进 href 就能让 javascript: 变成 XSS 入口 */
function safeSourceUrl(url: string): string {
  return /^https?:\/\//i.test(url) ? url : ''
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

function closeDropdownsOnOutside(e: MouseEvent) {
  if (approveRef.value && !approveRef.value.contains(e.target as Node)) approveOpen.value = false
  if (autoRef.value && !autoRef.value.contains(e.target as Node)) autoOpen.value = false
  if (modelRef.value && !modelRef.value.contains(e.target as Node)) modelOpen.value = false
}
onMounted(() => {
  document.addEventListener('mousedown', closeDropdownsOnOutside)
  // 模型列表要登录才能读：已登录（刷新页面后 restoreSession 完成）就直接拉一次
  if (isLoggedIn.value) void loadModels()
})
// 登录后刷新可选模型，登出作废缓存与选中项，避免下一个账号看到上一个的列表
watch(isLoggedIn, (v) => {
  if (v) void loadModels(true)
  else {
    clearModels()
    pickedModel.value = null
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', closeDropdownsOnOutside)
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
                <p class="text-[11px] text-stone-400 opacity-0 transition group-hover:opacity-100">{{ formatMsgTime(m.created_at) }}</p>
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
            <div v-else class="group max-w-[92%] min-w-0">
              <div v-if="m.tools.length" class="mb-2.5 flex flex-wrap gap-2">
                <span
                  v-for="t in m.tools"
                  :key="t"
                  class="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11.5px] text-stone-600"
                  :title="m.toolStates[t] === 'running' ? '执行中…' : undefined"
                >
                  <!-- 协议 v2 的 tool_start/tool_end：running 转圈，done 打勾；历史恢复无状态时保持静态钩子图 -->
                  <span
                    v-if="m.toolStates[t] === 'running'"
                    class="h-3 w-3 shrink-0 animate-spin rounded-full border-[1.5px] border-stone-300 border-t-stone-600"
                  ></span>
                  <svg
                    v-else-if="m.toolStates[t] === 'done'"
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    class="text-emerald-600"
                  >
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                  <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4z" />
                  </svg>
                  调用 {{ t }}
                </span>
              </div>

              <!-- 思考过程：只在深度档且后端真的返回了 reasoning 时出现；出正文后自动收起，可手动展开回看 -->
              <div v-if="m.reasoning" class="mb-2 overflow-hidden rounded-xl border border-stone-200/80 bg-stone-50/70">
                <button
                  type="button"
                  @click="toggleReasoning(i, m)"
                  class="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11.5px] text-stone-500 hover:text-stone-700 transition"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3a6 6 0 0 0-3.5 10.9c.4.3.6.7.6 1.1h5.8c0-.4.2-.8.6-1.1A6 6 0 0 0 12 3ZM9 18h6M10 21h4" />
                  </svg>
                  {{ m.streaming && !m.content ? '思考中…' : '已完成思考' }}
                  <span class="text-stone-400">· {{ m.reasoning.length }} 字</span>
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
                <p
                  v-show="isReasoningOpen(i, m)"
                  :ref="(el) => setReasoningRef(i, el)"
                  @scroll="onReasoningScroll(i, $event)"
                  class="max-h-64 overflow-y-auto scroll-thin whitespace-pre-wrap break-words px-3 pb-2.5 text-[12px] leading-[1.7] text-stone-500"
                >{{ m.reasoning }}</p>
              </div>

              <!-- 正文：流式 Markdown 渲染（markstream 对未闭合语法做了稳定部分渲染） -->
              <MarkdownRender
                v-if="m.content"
                mode="chat"
                :content="m.content"
                :final="!m.streaming"
                :is-dark="false"
                class="md-answer px-1 py-0.5 text-[13.5px] leading-[1.7] text-stone-700"
              />
              <div v-else-if="!m.streaming && !m.error" class="px-1 py-0.5 text-[13.5px] text-stone-400">（无内容）</div>

              <!-- 参考来源：工具 artifact 下发，编号与正文里的 [n] 同号；后端不落库，重进会话时为空 -->
              <div v-if="m.citations.length" class="mt-3 rounded-xl border border-stone-200/80 bg-stone-50/70 px-3 py-2.5">
                <div class="flex items-center gap-1.5 text-[11.5px] text-stone-500">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 4h6a2 2 0 0 1 2 2v13a1.5 1.5 0 0 0-1.5-1.5H4Z" />
                    <path d="M20 4h-5a2 2 0 0 0-2 2v13a1.5 1.5 0 0 1 1.5-1.5H20Z" />
                  </svg>
                  参考来源 · {{ m.citations.length }}
                  <span v-if="m.streaming" class="text-stone-400">仍在检索…</span>
                </div>
                <ul class="mt-1.5 space-y-0.5">
                  <li v-for="c in m.citations" :key="c.index">
                    <a
                      v-if="safeSourceUrl(c.url)"
                      :href="c.url"
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      :title="c.url"
                      class="-mx-1.5 block rounded-lg px-1.5 py-1 transition hover:bg-white"
                    >
                      <span class="flex items-baseline gap-1.5">
                        <span class="shrink-0 rounded-full border border-stone-200 bg-white px-1 text-[10.5px] leading-4 text-stone-500">{{ c.index }}</span>
                        <span class="min-w-0 truncate text-[12.5px] text-stone-700">{{ c.title || sourceDomain(c.url) || c.url }}</span>
                        <span v-if="c.kind === 'page'" class="shrink-0 text-[10.5px] text-stone-400">已读原文</span>
                      </span>
                      <p v-if="c.snippet" class="mt-0.5 line-clamp-2 pl-[27px] text-[11.5px] leading-[1.6] text-stone-500">{{ c.snippet }}</p>
                      <p class="mt-0.5 truncate pl-[27px] text-[11px] text-stone-400">
                        {{ sourceDomain(c.url) }}<span v-if="c.published_date"> · {{ c.published_date }}</span>
                      </p>
                    </a>
                    <!-- 地址不是 http(s)：只当文字展示，不给可点的链接 -->
                    <span v-else class="-mx-1.5 block truncate px-1.5 py-1 text-[12px] text-stone-500">{{ c.title || c.url }}</span>
                  </li>
                </ul>
              </div>

              <p v-if="m.error" class="mt-2 text-[12.5px] text-red-500">{{ m.error }}</p>
              <p v-else-if="m.streaming && !m.content && !m.reasoning" class="mt-2 text-[12.5px] text-stone-400">
                正在思考<span v-if="waited >= 3">，已等待 {{ waited }}s</span
                ><span v-if="waited >= 20">{{
                  m.thinking ? '（深度思考模式首字较慢，仍在生成）' : '（本轮是快速档，慢在上游排队）'
                }}</span><span class="dots"></span>
              </p>
              <p v-if="(m.content || m.error) && m.created_at" class="mt-1.5 px-1 text-[11px] text-stone-400 opacity-0 transition group-hover:opacity-100">{{ formatMsgTime(m.created_at) }}</p>
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
        {{ user?.username ? `${user.username}，想聊点什么？` : '想聊点什么？' }}
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

            <!-- 右侧：模型 / Auto / 麦克风 / 发送 -->
            <div class="flex items-center gap-1.5">
              <!-- 模型：只列管理员接入的（不含密钥），平铺不标平台 -->
              <div ref="modelRef" class="relative">
                <button
                  type="button"
                  @click="modelOpen = !modelOpen"
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
                  class="absolute right-0 bottom-10 z-30 w-60 max-h-72 overflow-y-auto scroll-thin rounded-xl bg-white border border-stone-200 shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="m in chatModels"
                    :key="m.platform + '/' + m.model"
                    type="button"
                    :disabled="!isUsable(m)"
                    @click="chooseModel(m)"
                    class="w-full text-left px-3 py-2 rounded-lg text-[12.5px] transition flex items-center justify-between gap-2"
                    :class="
                      !isUsable(m)
                        ? 'text-stone-300 cursor-not-allowed'
                        : pickedModel?.platform === m.platform && pickedModel?.model === m.model
                          ? 'bg-stone-100 text-stone-900 font-medium'
                          : 'text-stone-600 hover:bg-stone-100'
                    "
                    :title="isUsable(m) ? '' : m.unavailable_reason || '该模型构建失败，请联系管理员'"
                  >
                    <span class="truncate">{{ optionLabel(m) }}</span>
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
      :class="detailCollapsed ? 'w-11 py-4 items-center' : 'w-1/4 overflow-y-auto scroll-thin px-5 py-6'"
    >
      <!-- 折叠态：仅一个展开按钮的窄轨 -->
      <button
        v-if="detailCollapsed"
        type="button"
        @click="detailCollapsed = false"
        class="h-8 w-8 shrink-0 grid place-items-center rounded-lg text-stone-500 hover:bg-stone-200/70 hover:text-stone-700 transition"
        title="展开对话详情"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
      </button>

      <!-- 展开态 -->
      <template v-else>
        <div class="flex items-center justify-between">
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
      <div class="mt-5 space-y-5">
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

/* Markdown 正文微调：字号放大后同步松开块级间距，首尾元素不留多余外边距 */
.md-answer :deep(p) {
  margin: 0.6em 0;
}
.md-answer :deep(ul),
.md-answer :deep(ol) {
  margin: 0.6em 0;
  padding-left: 1.5em;
}
.md-answer :deep(li) {
  margin: 0.25em 0;
}
.md-answer :deep(h1),
.md-answer :deep(h2),
.md-answer :deep(h3),
.md-answer :deep(h4) {
  margin: 0.75em 0 0.4em;
  font-weight: 600;
  line-height: 1.35;
}
.md-answer :deep(pre) {
  margin: 0.65em 0;
  font-size: 14px;
}
.md-answer :deep(code) {
  font-size: 0.9em;
}
.md-answer :deep(:first-child) {
  margin-top: 0;
}
.md-answer :deep(:last-child) {
  margin-bottom: 0;
}
</style>
