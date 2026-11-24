<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuth } from '../stores/auth'

/** v-model 控制显隐；initialMode 决定打开时停留在登录还是注册页 */
const open = defineModel<boolean>({ required: true })
const props = defineProps<{ initialMode?: 'login' | 'register' }>()

const { login, register, loading, error } = useAuth()

const tab = ref<'login' | 'register'>('login')
const account = ref('')
const username = ref('')
const email = ref('')
const password = ref('')

// 每次打开重置表单与页签，避免残留上次输入
watch(open, (v) => {
  if (v) {
    tab.value = props.initialMode ?? 'login'
    account.value = ''
    username.value = ''
    email.value = ''
    password.value = ''
  }
})

function close() {
  open.value = false
}

async function submit() {
  if (loading.value) return
  const ok =
    tab.value === 'login'
      ? await login(account.value.trim(), password.value)
      : await register(username.value.trim(), email.value.trim(), password.value)
  if (ok) close()
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
        class="w-[min(92vw,380px)] rounded-2xl bg-[#F5F1E8] border border-[#EAE5D3] shadow-xl shadow-stone-900/10 p-6"
        @mousedown.stop
      >
        <!-- 头部 -->
        <div class="flex items-center justify-between">
          <h2 class="text-[17px] font-semibold text-[#2b2a22]">
            {{ tab === 'login' ? '欢迎回来' : '创建账号' }}
          </h2>
          <button
            type="button"
            @click="close"
            class="h-7 w-7 grid place-items-center rounded-lg text-[#6d6a52] hover:bg-black/5 transition"
            title="关闭"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        <!-- 页签切换 -->
        <div class="mt-4 flex rounded-xl bg-white/70 border border-[#EAE5D3] p-1 text-[13px] font-medium">
          <button
            type="button"
            @click="tab = 'login'"
            class="flex-1 h-8 rounded-lg transition"
            :class="tab === 'login' ? 'bg-[#333228] text-[#F7F3E4]' : 'text-[#4b4938] hover:bg-white'"
          >
            登录
          </button>
          <button
            type="button"
            @click="tab = 'register'"
            class="flex-1 h-8 rounded-lg transition"
            :class="tab === 'register' ? 'bg-[#333228] text-[#F7F3E4]' : 'text-[#4b4938] hover:bg-white'"
          >
            免费注册
          </button>
        </div>

        <!-- 表单 -->
        <form class="mt-4 space-y-3" @submit.prevent="submit">
          <label class="block">
            <span class="block text-[12px] font-medium text-[#4b4938] mb-1">
              {{ tab === 'login' ? '用户名或邮箱' : '用户名' }}
            </span>
            <input
              v-if="tab === 'login'"
              v-model="account"
              type="text"
              autocomplete="username"
              placeholder="请输入用户名或邮箱"
              class="w-full h-9 rounded-lg border border-[#cfc6ae] bg-white/80 px-3 text-[13px] text-[#2b2a22] outline-none focus:border-[#8a8666] focus:ring-2 focus:ring-[#D9A15B]/30 transition"
            />
            <input
              v-else
              v-model="username"
              type="text"
              autocomplete="username"
              placeholder="3-64 个字符"
              class="w-full h-9 rounded-lg border border-[#cfc6ae] bg-white/80 px-3 text-[13px] text-[#2b2a22] outline-none focus:border-[#8a8666] focus:ring-2 focus:ring-[#D9A15B]/30 transition"
            />
          </label>

          <label v-if="tab === 'register'" class="block">
            <span class="block text-[12px] font-medium text-[#4b4938] mb-1">邮箱</span>
            <input
              v-model="email"
              type="email"
              autocomplete="email"
              placeholder="you@example.com"
              class="w-full h-9 rounded-lg border border-[#cfc6ae] bg-white/80 px-3 text-[13px] text-[#2b2a22] outline-none focus:border-[#8a8666] focus:ring-2 focus:ring-[#D9A15B]/30 transition"
            />
          </label>

          <label class="block">
            <span class="block text-[12px] font-medium text-[#4b4938] mb-1">密码</span>
            <input
              v-model="password"
              type="password"
              :autocomplete="tab === 'login' ? 'current-password' : 'new-password'"
              placeholder="至少 6 位"
              class="w-full h-9 rounded-lg border border-[#cfc6ae] bg-white/80 px-3 text-[13px] text-[#2b2a22] outline-none focus:border-[#8a8666] focus:ring-2 focus:ring-[#D9A15B]/30 transition"
            />
          </label>

          <!-- 后端错误提示 -->
          <p
            v-if="error"
            class="rounded-lg bg-[#F6DCD3] border border-[#E7C0B2] px-3 py-2 text-[12px] text-[#8a3d24]"
          >
            {{ error }}
          </p>

          <button
            type="submit"
            :disabled="loading"
            class="w-full h-9 rounded-lg bg-[#333228] text-[13px] font-medium text-[#F7F3E4] hover:bg-[#4a4838] transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {{ loading ? '处理中…' : tab === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>
      </div>
    </div>
  </Teleport>
</template>
