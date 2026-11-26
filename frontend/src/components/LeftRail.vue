<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AuthDialog from './AuthDialog.vue'
import SettingsDialog from './SettingsDialog.vue'
import { listTools, type ToolDto } from '../api/settings'
import { useAuth } from '../stores/auth'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'
import { useUi } from '../stores/ui'
import { useWorkspace } from '../stores/workspace'

/** 侧边栏折叠状态：宽度由父容器控制，此处负责内容收放 */
const collapsed = defineModel<boolean>('collapsed', { required: true })

/** 顶部 Workspace 切换器（真数据：/workspaces，选中项持久化在 localStorage） */
const {
  workspaces,
  sessions,
  activeId,
  activeWorkspace,
  lastError,
  load: loadWorkspaces,
  select: selectWorkspace,
  loadSessions,
  create: createWs,
  rename: renameWs,
  remove: removeWs,
} = useWorkspace()
const wsOpen = ref(false)
const wsRef = ref<HTMLElement | null>(null)

/* 新建：下拉菜单与中部区块的 + 共用同一个内联输入态 */
const creating = ref(false)
const newName = ref('')
/* 重命名：正在改名的工作区 id + 草稿；删除直接 confirm */
const editingId = ref<number | null>(null)
const editName = ref('')

async function submitNew() {
  const name = newName.value.trim()
  if (!name) {
    creating.value = false
    return
  }
  const ws = await createWs(name)
  if (ws) {
    newName.value = ''
    creating.value = false
    selectWorkspace(ws.id) // 新建即切入，会话列表随之刷新
  }
}

async function commitRename() {
  const id = editingId.value
  const name = editName.value.trim()
  editingId.value = null
  if (id != null && name) await renameWs(id, name)
}

async function removeOne(w: { id: number; name: string; is_default: boolean }) {
  if (w.is_default) {
    lastError.value = '默认工作区不可删除'
    return
  }
  if (!window.confirm(`删除工作区「${w.name}」？其中的会话会保留，但变为未分组。`)) return
  await removeWs(w.id)
}

function startRename(w: { id: number; name: string }) {
  editingId.value = w.id
  editName.value = w.name
}

/* 历史会话：点击恢复进聊天区 */
const { goHome, goChat } = useUi()
const { loadSession, sessionId, reset: resetChat } = useChat()
const openingId = ref<number | null>(null)

// 对话中首次产生新会话（meta 事件）后刷新当前工作区的会话列表
watch(sessionId, (v, old) => {
  if (v && v !== old) void loadSessions()
})

async function openSession(s: {
  id: number
  platform: string
  model: string
  thinking: boolean
}) {
  if (openingId.value === s.id) return
  openingId.value = s.id
  lastError.value = ''
  try {
    await loadSession(s.id, { platform: s.platform, model: s.model, thinking: s.thinking })
    goChat() // 品牌首页态下点开历史会话也要回到对话区
  } catch (e) {
    lastError.value = e instanceof Error ? e.message : '打开会话失败，请确认已登录'
  } finally {
    openingId.value = null
  }
}

function formatDay(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const sameYear = d.getFullYear() === today.getFullYear()
  const md = `${d.getMonth() + 1}月${d.getDate()}日`
  return sameYear ? md : `${d.getFullYear()}年${md}`
}

/** 悬停时展示的精确时间：完整到秒（年-月-日 时:分:秒） */
function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function onDocMousedown(e: MouseEvent) {
  if (wsRef.value && !wsRef.value.contains(e.target as Node)) wsOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocMousedown))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocMousedown))

/** 主导航 */
const navItems = [
  {
    key: 'new-task',
    label: '新对话',
    icon: 'M12 5v14M5 12h14',
  },
  {
    key: 'attention',
    label: '我的关注',
    icon: 'M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
  },
  {
    key: 'search',
    label: '搜索',
    icon: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-3.2-3.2',
  },
]

/** 底部菜单 */
const bottomItems = [
  {
    key: 'tools',
    label: '工具',
    icon: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8Z',
  },
  {
    key: 'automations',
    label: '自动化',
    icon: 'M13 2 4 14h7l-2 8 9-12h-7l2-8Z',
  },
  {
    key: 'extensions',
    label: '扩展',
    icon: 'M4 7h5V4a1 1 0 1 1 2 0v3h5a1 1 0 1 1 0 2H9v5a1 1 0 1 1-2 0V9H4a1 1 0 1 1 0-2ZM15 14h3a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-3a2 2 0 0 1 2-2Z',
  },
  {
    key: 'more',
    label: '更多',
    icon: 'M5 12h14',
    dots: true,
  },
]

const activeNav = ref('new-task')

/** 底部「工具」悬停面板：首次悬停才拉接口，后端按当前已挂载的工具返回 */
const supportedTools = ref<ToolDto[]>([])
const toolsLoaded = ref(false)
const toolsLoading = ref(false)
const toolsOpen = ref(false)
const toolsPos = ref({ top: 0, left: 0 })
let toolsCloseTimer: ReturnType<typeof setTimeout> | null = null

/** 后端给的是 lucide 图标名，这里内联对应 path，按需扩展即可 */
const LUCIDE_PATHS: Record<string, string[]> = {
  globe: [
    'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',
    'M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20',
    'M2 12h20',
  ],
  'file-text': [
    'M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z',
    'M14 2v5h6',
    'M10 9H8',
    'M16 13H8',
    'M16 17H8',
  ],
  wrench: [
    'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8Z',
  ],
}

function toolIconPaths(icon: string): string[] {
  return LUCIDE_PATHS[icon] ?? LUCIDE_PATHS.wrench
}

async function loadSupportedTools(): Promise<void> {
  if (toolsLoaded.value || toolsLoading.value) return
  toolsLoading.value = true
  try {
    supportedTools.value = await listTools()
    toolsLoaded.value = true
  } catch {
    supportedTools.value = []
    toolsLoaded.value = false // 允许下次悬停重试，不把一次网络抖动固化成「暂无工具」
  } finally {
    toolsLoading.value = false
  }
}

function openToolsPanel(e: MouseEvent): void {
  if (toolsCloseTimer) {
    clearTimeout(toolsCloseTimer)
    toolsCloseTimer = null
  }
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const panelWidth = 192
  const left = rect.right + 10 + panelWidth > window.innerWidth
    ? Math.max(8, rect.left - panelWidth - 10)
    : rect.right + 10
  toolsPos.value = { top: Math.max(8, Math.min(rect.top, window.innerHeight - 200)), left }
  toolsOpen.value = true
  void loadSupportedTools()
}

function closeToolsSoon(): void {
  if (toolsCloseTimer) clearTimeout(toolsCloseTimer)
  toolsCloseTimer = setTimeout(() => {
    toolsOpen.value = false
    toolsCloseTimer = null
  }, 120)
}

function cancelCloseTools(): void {
  if (toolsCloseTimer) {
    clearTimeout(toolsCloseTimer)
    toolsCloseTimer = null
  }
}

onBeforeUnmount(() => {
  if (toolsCloseTimer) clearTimeout(toolsCloseTimer)
})

function onBottomEnter(item: { key: string }, e: MouseEvent): void {
  if (item.key === 'tools') openToolsPanel(e)
}

function onBottomLeave(item: { key: string }): void {
  if (item.key === 'tools') closeToolsSoon()
}

/** 主导航点击：新对话清空当前聊天回到空白画布，其余项暂只切换高亮 */
function onNavClick(key: string) {
  activeNav.value = key
  if (key === 'new-task') {
    resetChat()
    goChat()
  }
}

/** 登录态：接后端 /auth/*（token 存 localStorage，用户信息来自 store） */
const { user, isLoggedIn, isAdmin, restoreSession } = useAuth()

const dialogOpen = ref(false)
const dialogMode = ref<'login' | 'register'>('login')
const settingsOpen = ref(false)
const { load: loadLlm } = useLlm()

function openSettings() {
  settingsOpen.value = true
}

function openLogin() {
  dialogMode.value = 'login'
  dialogOpen.value = true
}
function openRegister() {
  dialogMode.value = 'register'
  dialogOpen.value = true
}

onMounted(() => {
  restoreSession()
  // 不在这里拉 LLM 配置：此刻登录态还没恢复完，而且普通用户拉了只会拿到 403
  loadWorkspaces()
})

// 登录后拉一次工作区（模型配置只管理员需要）；退出时清本地列表（服务端数据不动）
watch(isLoggedIn, (v) => {
  if (v) {
    if (isAdmin.value) loadLlm()
    loadWorkspaces()
  } else {
    useWorkspace().clear()
  }
})
</script>

<template>
  <aside
    class="h-full flex flex-col overflow-hidden bg-gradient-to-b from-[#F7EDD3] via-[#EBE8C9] to-[#CBDCC3] border-r border-[#DAD6BE] select-none"
  >
    <!-- 顶部：AskSource Logo + Workspace 切换 + 折叠按钮（折叠时仅保留折叠按钮） -->
    <div
      class="shrink-0 flex items-center gap-2 px-4 pt-4 pb-2"
      :class="collapsed ? 'justify-center px-2' : ''"
    >
      <!-- Logo（折叠时整体隐藏）：点击回到品牌首页 -->
      <div
        v-if="!collapsed"
        class="flex items-center gap-2.5 select-none cursor-pointer rounded-lg -mx-1 px-1 hover:bg-white/50 transition"
        title="首页"
        @click="goHome()"
      >
        <svg width="32" height="32" viewBox="0 0 32 32" aria-label="AskSource logo">
          <defs>
            <linearGradient id="as-mark" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#3E3A33" />
              <stop offset="100%" stop-color="#5a5446" />
            </linearGradient>
          </defs>
          <!-- 背景圆角方块 -->
          <rect x="1" y="1" width="30" height="30" rx="9" fill="url(#as-mark)" />
          <!-- 原创 A 字形（抽象山峰 + 横杠） -->
          <path
            d="M9 23 L16 9 L23 23"
            fill="none"
            stroke="#F7F3E4"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M12 19 H20"
            stroke="#F7F3E4"
            stroke-width="2.2"
            stroke-linecap="round"
          />
          <!-- 右上角琥珀色小点（象征 source / spark） -->
          <circle cx="24.5" cy="8" r="2.2" fill="#D9A15B" />
        </svg>
        <span
          v-if="!collapsed"
          class="text-[14px] font-semibold tracking-tight text-[#2b2a22]"
        >
          Ask<span class="text-[#6d6a52]">Source</span>
        </span>
      </div>
      <!-- Workspace 切换器（填充 Logo 与折叠按钮之间的空隙） -->
      <div v-if="!collapsed" ref="wsRef" class="relative min-w-0 flex-1">
        <button
          type="button"
          @click="wsOpen = !wsOpen"
          class="w-full h-8 flex items-center gap-1.5 px-2.5 rounded-lg text-[#4b4938] hover:bg-white/60 transition"
          :class="wsOpen ? 'bg-white/70 shadow-[0_1px_2px_rgba(90,80,60,0.05)]' : ''"
          title="切换工作区"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-60">
            <rect x="3" y="4" width="18" height="13" rx="2" />
            <path d="M8.5 21h7M12 17v4" />
          </svg>
          <span class="min-w-0 flex-1 text-left text-[12.5px] font-medium truncate">
            {{ activeWorkspace?.name || (isLoggedIn ? '加载中…' : '未登录') }}
          </span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0 opacity-50" stroke-linecap="round">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        <div
          v-if="wsOpen"
          class="absolute left-0 top-10 z-30 w-52 rounded-xl bg-white border border-[#EAE5D3] shadow-lg shadow-stone-900/5 p-1.5"
        >
          <p class="px-2.5 pt-1 pb-1.5 text-[10.5px] font-medium tracking-[0.12em] uppercase text-[#a4a190]">
            工作区
          </p>
          <div
            v-for="w in workspaces"
            :key="w.id"
            class="group flex items-center rounded-lg transition"
            :class="
              w.id === activeId
                ? 'bg-[#F2EDE1] text-[#2b2a22]'
                : 'text-[#4b4938] hover:bg-[#F7F3E9]'
            "
          >
            <!-- 改名态：行内输入，Enter/失焦提交，Esc 取消 -->
            <input
              v-if="editingId === w.id"
              v-model="editName"
              autofocus
              @keydown.enter="commitRename"
              @keydown.esc="editingId = null"
              @blur="commitRename"
              class="flex-1 min-w-0 mx-2.5 my-1 px-1.5 py-1 rounded-md text-[12.5px] bg-white border border-[#D8D2BC] outline-none"
            />
            <button
              v-else
              type="button"
              @click="((selectWorkspace(w.id)), (wsOpen = false))"
              class="flex-1 min-w-0 text-left px-2.5 py-2 rounded-lg text-[12.5px] font-medium truncate"
              :class="w.id === activeId ? 'font-semibold' : ''"
            >
              {{ w.name }}
            </button>
            <template v-if="editingId !== w.id">
              <button
                type="button"
                @click.stop="startRename(w)"
                class="opacity-0 group-hover:opacity-100 h-7 w-7 mr-0.5 grid place-items-center rounded-md text-[#8a8872] hover:bg-white/80 transition"
                title="重命名"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                </svg>
              </button>
              <button
                v-if="!w.is_default"
                type="button"
                @click.stop="removeOne(w)"
                class="opacity-0 group-hover:opacity-100 h-7 w-7 mr-1 grid place-items-center rounded-md text-[#8a8872] hover:text-red-500 hover:bg-white/80 transition"
                title="删除"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                </svg>
              </button>
            </template>
          </div>
          <!-- 新建入口：关掉下拉，光标到中部区块的内联输入框 -->
          <div class="my-1 border-t border-[#F0EBDA]" />
          <button
            type="button"
            @click="((wsOpen = false), (creating = true))"
            class="w-full text-left px-2.5 py-2 rounded-lg text-[12.5px] text-[#6d6a52] hover:bg-[#F7F3E9] transition"
          >
            + 新建工作区
          </button>
        </div>
      </div>
      <!-- 折叠 / 展开侧边栏 -->
      <button
        type="button"
        class="h-7 w-7 shrink-0 grid place-items-center rounded-lg text-[#5b5945] hover:bg-black/5 transition"
        :class="collapsed ? '' : 'ml-auto'"
        :title="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="collapsed = !collapsed"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="transition-transform duration-300"
          :class="collapsed ? 'rotate-180' : ''"
        >
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M9 4v16" />
        </svg>
      </button>
    </div>

    <!-- 主导航 -->
    <nav
      class="shrink-0 mt-4 space-y-0.5"
      :class="collapsed ? 'px-2' : 'px-3'"
    >
      <button
        v-for="item in navItems"
        :key="item.key"
        type="button"
        @click="onNavClick(item.key)"
        class="w-full flex items-center rounded-xl font-medium transition"
        :class="[
          collapsed ? 'justify-center h-9' : 'gap-2.5 px-3 py-2 text-[13px]',
          activeNav === item.key
            ? 'bg-white/70 text-[#2b2a22] shadow-[0_1px_2px_rgba(90,80,60,0.05)]'
            : 'text-[#4b4938] hover:bg-white/50',
        ]"
        :title="item.label"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-70">
          <path :d="item.icon" />
        </svg>
        <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
      </button>
    </nav>

    <!-- Workspaces -->
    <section
      class="mt-5 flex-1 min-h-0 flex flex-col"
      :class="collapsed ? 'px-2' : 'px-3'"
    >
      <header class="flex items-center pb-1.5" :class="collapsed ? 'justify-center' : 'justify-between px-2'">
        <span v-if="!collapsed" class="text-[10.5px] font-medium tracking-[0.14em] uppercase text-[#6d6a52] truncate">
          {{ activeWorkspace?.name || '工作区' }}
        </span>
        <button
          type="button"
          @click="isLoggedIn ? ((creating = true)) : openLogin()"
          class="h-6 w-6 grid place-items-center rounded-md text-[#4b4938] hover:bg-white/60 transition"
          :title="isLoggedIn ? '新建工作区' : '登录后新建工作区'"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </header>

      <div v-if="!collapsed" class="flex-1 min-h-0 overflow-y-auto scroll-thin px-1 space-y-0.5">
        <!-- 错误就近常驻：包括工作区写操作与打开历史会话失败 -->
        <p v-if="lastError" class="px-1 py-1 text-[11px] text-red-500">{{ lastError }}</p>
        <!-- 新建工作区：内联输入（由本区块 + 或下拉菜单触发） -->
        <template v-if="creating">
          <input
            v-model="newName"
            autofocus
            placeholder="工作区名称，Enter 创建"
            @keydown.enter="submitNew"
            @keydown.esc="((creating = false), (newName = ''))"
            @blur="creating = newName.trim() ? creating : false"
            class="w-full px-2.5 py-2 rounded-lg text-[12.5px] bg-white border border-[#D8D2BC] outline-none placeholder:text-[#b5b19c]"
          />
        </template>

        <!-- 当前工作区下的会话列表 -->
        <button
          v-for="s in sessions"
          :key="s.id"
          type="button"
          @click="openSession(s)"
          class="group w-full px-2 py-2 rounded-lg text-left transition"
          :class="s.id === openingId ? 'bg-white/70' : 'hover:bg-white/50'"
          :title="s.title || '未命名对话'"
        >
          <div class="flex items-center gap-2">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-50">
              <path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z" />
            </svg>
            <span class="min-w-0 flex-1 text-[12.5px] text-[#4b4938] truncate">{{ s.title || '未命名对话' }}</span>
            <span class="shrink-0 text-[10px] text-[#a4a190]">{{ formatDay(s.updated_at) }}</span>
          </div>
          <!-- 悬停时下方展开精确时间 -->
          <p class="overflow-hidden max-h-0 opacity-0 group-hover:max-h-5 group-hover:opacity-100 group-hover:mt-1 transition-all duration-200 pl-[21px] text-[10.5px] leading-none text-[#8a8872]">
            最后活跃 · {{ formatTime(s.updated_at) }}
          </p>
        </button>

        <div
          v-if="!creating && isLoggedIn && !sessions.length"
          class="h-full grid place-items-center text-center px-4"
        >
          <p class="text-[12px] text-[#7d7a60] leading-relaxed">
            本工作区还没有对话 :)<br />发一条消息就会出现在这里
          </p>
        </div>
        <div v-else-if="!creating && !isLoggedIn" class="h-full grid place-items-center text-center px-4">
          <p class="text-[12px] text-[#7d7a60] leading-relaxed">登录后查看工作区会话</p>
        </div>
      </div>
      <div v-else class="flex-1 min-h-0" />
    </section>

    <!-- 底部：菜单 + 卡片 + 账号 -->
    <div
      class="shrink-0 pb-3 mt-3"
      :class="collapsed ? 'px-2' : 'px-3'"
    >
      <ul class="space-y-0.5">
        <li v-for="item in bottomItems" :key="item.key">
          <button
            type="button"
            class="w-full flex items-center rounded-lg text-[12.5px] text-[#4b4938] hover:bg-white/50 transition"
            :class="collapsed ? 'justify-center h-8' : 'gap-2.5 px-3 py-2'"
            :title="item.key === 'tools' ? '当前支持的工具' : item.label"
            @mouseenter="onBottomEnter(item, $event)"
            @mouseleave="onBottomLeave(item)"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-70">
              <path :d="item.icon" />
              <template v-if="item.dots">
                <circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" />
                <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                <circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" />
              </template>
            </svg>
            <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          </button>
        </li>
      </ul>

      <!-- 未登录：登录 / 免费注册 -->
      <div
        v-if="!isLoggedIn"
        class="mt-3 flex"
        :class="collapsed ? 'flex-col items-center gap-1.5' : 'gap-2 px-1'"
      >
        <template v-if="!collapsed">
          <button
            type="button"
            @click="openLogin"
            class="flex-1 h-9 rounded-lg border border-[#cfc6ae] bg-white/70 text-[12.5px] font-medium text-[#2b2a22] hover:bg-white transition"
          >
            登录
          </button>
          <button
            type="button"
            @click="openRegister"
            class="flex-1 h-9 rounded-lg bg-[#333228] text-[12.5px] font-medium text-[#F7F3E4] hover:bg-[#4a4838] transition"
          >
            免费注册
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            @click="openLogin"
            class="h-8 w-8 grid place-items-center rounded-lg text-[#5b5945] hover:bg-white/60 transition"
            title="登录"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21a8 8 0 0 1 16 0" />
            </svg>
          </button>
          <button
            type="button"
            @click="openRegister"
            class="h-8 w-8 grid place-items-center rounded-lg bg-[#333228] text-[#F7F3E4] hover:bg-[#4a4838] transition"
            title="免费注册"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </template>
      </div>

      <!-- 已登录：账号 -->
      <div
        v-else
        class="mt-3 flex items-center"
        :class="collapsed ? 'flex-col gap-1.5' : 'gap-2 px-1'"
      >
        <div
          class="h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-[#D9C9A3] to-[#7C9A5C] grid place-items-center text-[12px] font-semibold text-white"
          :title="user?.username"
        >
          {{ (user?.username || '?').charAt(0).toUpperCase() }}
        </div>
        <span v-if="!collapsed" class="min-w-0 flex-1 leading-tight">
          <span class="block text-[12.5px] font-medium text-[#2b2a22] truncate">{{ user?.username }}</span>
          <span class="block text-[10.5px] text-[#6d6a52] truncate">{{ user?.email }}</span>
        </span>
        <!-- 模型配置（密钥）只有管理员能改，普通用户看不到这个入口 -->
        <button
          v-if="!collapsed && isAdmin"
          type="button"
          @click="openSettings"
          class="h-7 w-7 grid place-items-center rounded-lg text-[#5b5945] hover:bg-white/60 transition"
          title="设置"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 登录 / 注册弹窗 -->
    <AuthDialog v-model="dialogOpen" :initial-mode="dialogMode" />

    <!-- 设置弹窗（LLM 配置） -->
    <SettingsDialog v-model="settingsOpen" />

    <!-- 工具列表 Teleport 到 body：侧边栏自身 overflow-hidden，浮层放里面会被裁掉 -->
    <Teleport to="body">
      <div
        v-if="toolsOpen"
        role="tooltip"
        class="fixed z-[100] max-h-[70vh] w-48 overflow-y-auto rounded-xl border border-[#E6E0CC] bg-white p-2.5 shadow-[0_12px_36px_rgba(45,42,30,0.16)]"
        :style="{ top: `${toolsPos.top}px`, left: `${toolsPos.left}px` }"
        @mouseenter="cancelCloseTools"
        @mouseleave="toolsOpen = false"
      >
        <p class="mb-1.5 px-1 text-[11.5px] font-semibold text-[#3f3d30]">当前支持的工具</p>
        <p v-if="toolsLoading && !supportedTools.length" class="px-1 py-2 text-[11px] text-[#8a8872]">
          加载中…
        </p>
        <p v-else-if="!supportedTools.length" class="px-1 py-2 text-[11px] text-[#8a8872]">
          暂无可用工具
        </p>
        <ul v-else class="space-y-0.5">
          <li
            v-for="tool in supportedTools"
            :key="tool.name"
            class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] text-[#4b4938] hover:bg-[#F7F3E9]"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-70">
              <path v-for="d in toolIconPaths(tool.icon)" :key="d" :d="d" />
            </svg>
            <span class="truncate">{{ tool.label || tool.name }}</span>
          </li>
        </ul>
      </div>
    </Teleport>
  </aside>
</template>
