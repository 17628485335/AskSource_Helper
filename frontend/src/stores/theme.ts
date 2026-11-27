/**
 * 主题偏好：浅色 / 深色 / 跟随系统。
 * 只存当前浏览器的 localStorage；通过 html[data-theme] 驱动 style.css 的 CSS 变量换肤。
 */
import { ref, watch } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'asksource_theme'

function readStored(): ThemeMode {
  const v = localStorage.getItem(STORAGE_KEY)
  return v === 'dark' || v === 'system' ? v : 'light'
}

const mode = ref<ThemeMode>(readStored())
const systemDark = ref(false)
let media: MediaQueryList | null = null

function apply() {
  const effective =
    mode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : mode.value
  document.documentElement.dataset.theme = effective
}

/** 在 main.ts 挂载前调用：尽早打上 data-theme，避免首屏闪一下浅色 */
export function initTheme(): void {
  if (media) return
  media = window.matchMedia('(prefers-color-scheme: dark)')
  systemDark.value = media.matches
  media.addEventListener('change', (e) => {
    systemDark.value = e.matches
    apply()
  })
  apply()
}

watch(mode, (v) => {
  localStorage.setItem(STORAGE_KEY, v)
  apply()
})

export function useTheme() {
  return {
    mode,
    setMode: (v: ThemeMode) => {
      mode.value = v
    },
  }
}
