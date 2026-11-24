<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 侧边栏折叠状态：宽度由父容器控制，此处负责内容收放 */
const collapsed = defineModel<boolean>('collapsed', { required: true })

/** 顶部 Workspace 切换器 */
const workspaces = ['Personal', 'Product Team', 'Research', 'DevOps']
const workspaceIdx = ref(0)
const wsOpen = ref(false)
const wsRef = ref<HTMLElement | null>(null)

function onDocMousedown(e: MouseEvent) {
  if (wsRef.value && !wsRef.value.contains(e.target as Node)) wsOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocMousedown))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocMousedown))

/** 主导航 */
const navItems = [
  {
    key: 'new-task',
    label: 'New Task',
    icon: 'M12 5v14M5 12h14',
  },
  {
    key: 'attention',
    label: 'My Attention',
    icon: 'M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
  },
  {
    key: 'search',
    label: 'Search',
    icon: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-3.2-3.2',
  },
]

/** 底部菜单 */
const bottomItems = [
  {
    key: 'sites',
    label: 'Sites',
    icon: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3.6 9h16.8M3.6 15h16.8M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z',
  },
  {
    key: 'automations',
    label: 'Automations',
    icon: 'M13 2 4 14h7l-2 8 9-12h-7l2-8Z',
  },
  {
    key: 'extensions',
    label: 'Extensions',
    icon: 'M4 7h5V4a1 1 0 1 1 2 0v3h5a1 1 0 1 1 0 2H9v5a1 1 0 1 1-2 0V9H4a1 1 0 1 1 0-2ZM15 14h3a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-3a2 2 0 0 1 2-2Z',
  },
  {
    key: 'more',
    label: 'More',
    icon: 'M5 12h14',
    dots: true,
  },
]

const activeNav = ref('new-task')

/** 登录态（本地模拟）：未登录时底部显示登录/免费注册，登录后显示账号信息 */
const loggedIn = ref(false)

/** 演示用：模拟登录/注册成功（接入真实鉴权后替换为路由跳转/OAuth） */
function handleLogin() {
  loggedIn.value = true
}
function handleRegister() {
  loggedIn.value = true
}

/** 演示用：账号菜单切换回未登录态 */
function handleLogout() {
  loggedIn.value = false
}
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
      <!-- Logo（折叠时整体隐藏） -->
      <div v-if="!collapsed" class="flex items-center gap-2.5 select-none">
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
          class="text-[15px] font-semibold tracking-tight text-[#2b2a22]"
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
          title="Switch workspace"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-60">
            <rect x="3" y="4" width="18" height="13" rx="2" />
            <path d="M8.5 21h7M12 17v4" />
          </svg>
          <span class="min-w-0 flex-1 text-left text-[12.5px] font-medium truncate">
            {{ workspaces[workspaceIdx] }}
          </span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0 opacity-50" stroke-linecap="round">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        <div
          v-if="wsOpen"
          class="absolute left-0 top-10 z-30 w-52 rounded-xl bg-white border border-[#EAE5D3] shadow-lg shadow-stone-900/5 p-1.5"
        >
          <p class="px-2.5 pt-1 pb-1.5 text-[10.5px] font-semibold tracking-[0.12em] uppercase text-[#a4a190]">
            Workspaces
          </p>
          <button
            v-for="(w, i) in workspaces"
            :key="w"
            type="button"
            @click="((workspaceIdx = i), (wsOpen = false))"
            class="w-full text-left px-2.5 py-1.5 rounded-lg text-[12.5px] transition"
            :class="
              i === workspaceIdx
                ? 'bg-[#F2EDE1] text-[#2b2a22] font-medium'
                : 'text-[#4b4938] hover:bg-[#F7F3E9]'
            "
          >
            {{ w }}
          </button>
          <div class="my-1 border-t border-[#F0EBDA]" />
          <button
            type="button"
            class="w-full text-left px-2.5 py-1.5 rounded-lg text-[12.5px] text-[#6d6a52] hover:bg-[#F7F3E9] transition"
          >
            Manage workspaces…
          </button>
        </div>
      </div>
      <!-- 折叠 / 展开侧边栏 -->
      <button
        type="button"
        class="h-7 w-7 shrink-0 grid place-items-center rounded-lg text-[#5b5945] hover:bg-black/5 transition"
        :class="collapsed ? '' : 'ml-auto'"
        :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
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
        @click="activeNav = item.key"
        class="w-full flex items-center rounded-xl font-medium transition"
        :class="[
          collapsed ? 'justify-center h-9' : 'gap-2.5 px-3 py-2 text-[13px]',
          activeNav === item.key
            ? 'bg-white/70 text-[#2b2a22] shadow-[0_1px_2px_rgba(90,80,60,0.05)]'
            : 'text-[#4b4938] hover:bg-white/50',
        ]"
        :title="item.label"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-70">
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
        <span v-if="!collapsed" class="text-[10.5px] font-semibold tracking-[0.14em] uppercase text-[#6d6a52]">
          Workspaces
        </span>
        <button
          type="button"
          class="h-6 w-6 grid place-items-center rounded-md text-[#4b4938] hover:bg-white/60 transition"
          title="New workspace"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </header>

      <div v-if="!collapsed" class="flex-1 min-h-0 grid place-items-center text-center px-4">
        <p class="text-[12px] text-[#7d7a60] leading-relaxed">
          No task data yet :)
        </p>
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
            :class="collapsed ? 'justify-center h-8' : 'gap-2.5 px-3 py-1.5'"
            :title="item.label"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 opacity-70">
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

      <!-- Get Bonus Credits -->
      <button
        type="button"
        class="mt-3 flex items-center rounded-2xl bg-white/70 backdrop-blur-sm border border-white/80 hover:bg-white/85 transition text-left shadow-[0_1px_2px_rgba(90,80,60,0.04)]"
        :class="collapsed ? 'justify-center p-2' : 'w-full gap-2.5 p-3'"
        title="Get Bonus Credits"
      >
        <span class="h-8 w-8 shrink-0 grid place-items-center rounded-xl bg-gradient-to-br from-[#F3DFA8] to-[#B8975A] text-white">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="8" width="18" height="4" rx="1" />
            <path d="M5 12v8h14v-8M12 8v12M12 8s-2-4-5-4a2.5 2.5 0 0 0 0 5M12 8s2-4 5-4a2.5 2.5 0 0 1 0 5" />
          </svg>
        </span>
        <span v-if="!collapsed" class="min-w-0 flex-1 leading-tight">
          <span class="block text-[12.5px] font-semibold text-[#2b2a22]">Get Bonus Credits</span>
          <span class="block text-[11px] text-[#6d6a52] mt-0.5 truncate">
            Invite friends, earn extra usage
          </span>
        </span>
        <svg v-if="!collapsed" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" class="text-[#6d6a52] shrink-0">
          <path d="m9 6 6 6-6 6" />
        </svg>
      </button>

      <!-- 未登录：登录 / 免费注册 -->
      <div
        v-if="!loggedIn"
        class="mt-3 flex"
        :class="collapsed ? 'flex-col items-center gap-1.5' : 'gap-2 px-1'"
      >
        <template v-if="!collapsed">
          <button
            type="button"
            @click="handleLogin"
            class="flex-1 h-8 rounded-lg border border-[#cfc6ae] bg-white/70 text-[12.5px] font-medium text-[#2b2a22] hover:bg-white transition"
          >
            登录
          </button>
          <button
            type="button"
            @click="handleRegister"
            class="flex-1 h-8 rounded-lg bg-[#333228] text-[12.5px] font-medium text-[#F7F3E4] hover:bg-[#4a4838] transition"
          >
            免费注册
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            @click="handleLogin"
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
            @click="handleRegister"
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
        <button
          type="button"
          class="h-8 w-8 shrink-0 rounded-full bg-gradient-to-br from-[#D9C9A3] to-[#7C9A5C] grid place-items-center text-[12px] font-semibold text-white"
          :title="collapsed ? 'Jay · 点击退出（演示）' : undefined"
          @click="handleLogout"
        >
          J
        </button>
        <span v-if="!collapsed" class="min-w-0 flex-1 leading-tight">
          <span class="block text-[12.5px] font-semibold text-[#2b2a22] truncate">Jay</span>
          <span class="block text-[10.5px] text-[#6d6a52] truncate">jay@asksource.ai</span>
        </span>
        <button
          v-if="!collapsed"
          type="button"
          class="h-7 w-7 grid place-items-center rounded-lg text-[#5b5945] hover:bg-white/60 transition"
          title="Settings"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
          </svg>
        </button>
      </div>
    </div>
  </aside>
</template>
