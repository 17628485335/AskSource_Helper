<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/* ---------------- 品牌 & 副标题下拉 ---------------- */
const assistantNames = ['AskSource', 'Qwen', 'DeepSeek', 'GPT-4o', 'Claude']
const assistantIndex = ref(0)
const assistantOpen = ref(false)
const assistantRef = ref<HTMLElement | null>(null)

function pickAssistant(i: number) {
  assistantIndex.value = i
  assistantOpen.value = false
}
function onClickOutside(e: MouseEvent) {
  if (assistantRef.value && !assistantRef.value.contains(e.target as Node)) {
    assistantOpen.value = false
  }
}
onMounted(() => document.addEventListener('mousedown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))

/* ---------------- 热力图 Sessions / Credits ---------------- */
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

/** 强度对应的类（避免依赖动态 Tailwind 字符串） */
const levelClass: Record<number, string> = {
  0: 'bg-[#F1EBD9]',
  1: 'bg-[#DCE1BE]',
  2: 'bg-[#B3C58C]',
  3: 'bg-[#86A964]',
  4: 'bg-[#4F6B39]',
}

/** 月份标签：从 12 月起，共 12 个月 */
const monthLabels = ['Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov']
/** 每列属于哪一月：48 周 / 12 月 ≈ 每 4 周一个月份标签 */
const monthStartCols = monthLabels.map((_, i) => Math.floor((i * WEEKS) / 12))

/* ---------------- 输入框 ---------------- */
const draft = ref('')
const approveIdx = ref(0)
const approveOptions = ['Auto approve', 'Ask every time', 'Read-only']
const approveOpen = ref(false)
const approveRef = ref<HTMLElement | null>(null)

const autoIdx = ref(0)
const autoOptions = ['Auto', 'Fast', 'Deep']
const autoOpen = ref(false)
const autoRef = ref<HTMLElement | null>(null)

const micOn = ref(false)

function toggleMic() {
  micOn.value = !micOn.value
}

function submit() {
  if (!draft.value.trim()) return
  console.log('send:', draft.value)
  draft.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function closeDropdownsOnOutside(e: MouseEvent) {
  if (approveRef.value && !approveRef.value.contains(e.target as Node)) approveOpen.value = false
  if (autoRef.value && !autoRef.value.contains(e.target as Node)) autoOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', closeDropdownsOnOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', closeDropdownsOnOutside))
</script>

<template>
  <section class="relative h-full flex flex-col bg-white overflow-hidden">
    <!-- 中间可滚动内容区 -->
    <div class="flex-1 min-h-0 overflow-y-auto scroll-thin px-6 pt-12 pb-4">
      <div class="mx-auto max-w-[860px] flex flex-col items-center">
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
        <h1 class="mt-6 text-[38px] leading-tight font-semibold tracking-tight text-[#1e1e1b]">
          Beyond Coding
        </h1>

        <!-- 带下拉的副标题 -->
        <div class="mt-2 text-[15px] text-[#5e5b4e] flex items-center gap-1.5 flex-wrap justify-center">
          <span>What can</span>
          <div ref="assistantRef" class="relative inline-block">
            <button
              type="button"
              @click="assistantOpen = !assistantOpen"
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg hover:bg-[#F5F1E3] transition text-[#2b2a22] font-medium"
            >
              {{ assistantNames[assistantIndex] }}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[#a4a190]" stroke-linecap="round">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            <div
              v-if="assistantOpen"
              class="absolute left-1/2 -translate-x-1/2 top-8 z-30 w-44 rounded-xl bg-white border border-[#EAE5D3] shadow-lg shadow-stone-900/5 p-1.5"
            >
              <button
                v-for="(n, i) in assistantNames"
                :key="n"
                type="button"
                @click="pickAssistant(i)"
                class="w-full text-left px-2.5 py-1.5 rounded-lg text-[12.5px] transition"
                :class="
                  i === assistantIndex
                    ? 'bg-[#F2EDE1] text-[#2b2a22] font-medium'
                    : 'text-[#4b4938] hover:bg-[#F7F3E9]'
                "
              >
                {{ n }}
              </button>
            </div>
          </div>
          <span>help you build?</span>
        </div>

        <!-- 热力图卡片 -->
        <div
          class="mt-10 w-full rounded-2xl border border-[#EDE7D2] bg-white p-5 shadow-[0_1px_3px_rgba(90,80,60,0.04)]"
        >
          <!-- 卡片头 -->
          <div class="flex items-center justify-between gap-3">
            <div class="inline-flex gap-1 p-0.5 rounded-full bg-[#F5F1E3] border border-[#EDE7D2]">
              <button
                type="button"
                @click="heatTab = 'sessions'"
                class="px-3 py-1 rounded-full text-[11.5px] font-medium transition"
                :class="
                  heatTab === 'sessions'
                    ? 'bg-white text-[#2b2a22] shadow-sm'
                    : 'text-[#7a7561] hover:text-[#2b2a22]'
                "
              >
                Sessions
              </button>
              <button
                type="button"
                @click="heatTab = 'credits'"
                class="px-3 py-1 rounded-full text-[11.5px] font-medium transition"
                :class="
                  heatTab === 'credits'
                    ? 'bg-white text-[#2b2a22] shadow-sm'
                    : 'text-[#7a7561] hover:text-[#2b2a22]'
                "
              >
                Credits
              </button>
            </div>

            <div class="text-[11px] text-[#8a8872] tracking-wide">Dec 2025 – Nov 2026</div>
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
                <span class="mr-1">Less</span>
                <span v-for="l in [0, 1, 2, 3, 4]" :key="l" class="w-[10px] h-[10px] rounded-[3px]" :class="levelClass[l]" />
                <span class="ml-1">More</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部输入框 -->
    <div class="shrink-0 px-6 pb-5">
      <div class="mx-auto max-w-[760px]">
        <div
          class="rounded-2xl border border-[#E8E3D1] bg-white shadow-[0_6px_24px_rgba(140,120,80,0.08)] overflow-hidden"
        >
          <!-- 上行：文本输入 -->
          <textarea
            v-model="draft"
            @keydown="onKeydown"
            rows="2"
            placeholder="Ask anything, or describe what you want to build…"
            class="w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[14px] leading-relaxed text-[#2b2a22] placeholder:text-[#a4a190] outline-none"
          />

          <!-- 下行：工具条 -->
          <div class="flex items-center justify-between gap-2 px-2.5 pb-2.5 pt-1">
            <!-- 左侧：+ / 附件 / Auto approve -->
            <div class="flex items-center gap-1 min-w-0">
              <button
                type="button"
                class="h-8 w-8 grid place-items-center rounded-lg text-[#5e5b4e] hover:bg-[#F5F1E3] hover:text-[#2b2a22] transition"
                title="Add"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
              <button
                type="button"
                class="h-8 w-8 grid place-items-center rounded-lg text-[#5e5b4e] hover:bg-[#F5F1E3] hover:text-[#2b2a22] transition"
                title="Attach"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>

              <div ref="approveRef" class="relative">
                <button
                  type="button"
                  @click="approveOpen = !approveOpen"
                  class="h-8 px-2.5 inline-flex items-center gap-1 rounded-lg text-[12px] text-[#4b4938] hover:bg-[#F5F1E3] transition"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70">
                    <path d="M9 12l2 2 4-4" />
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                  {{ approveOptions[approveIdx] }}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[#a4a190]" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="approveOpen"
                  class="absolute left-0 bottom-9 z-30 w-44 rounded-xl bg-white border border-[#EAE5D3] shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="(o, i) in approveOptions"
                    :key="o"
                    type="button"
                    @click="((approveIdx = i), (approveOpen = false))"
                    class="w-full text-left px-2.5 py-1.5 rounded-lg text-[12.5px] transition"
                    :class="
                      i === approveIdx
                        ? 'bg-[#F2EDE1] text-[#2b2a22] font-medium'
                        : 'text-[#4b4938] hover:bg-[#F7F3E9]'
                    "
                  >
                    {{ o }}
                  </button>
                </div>
              </div>
            </div>

            <!-- 右侧：Auto / 麦克风 / 发送 -->
            <div class="flex items-center gap-1">
              <div ref="autoRef" class="relative">
                <button
                  type="button"
                  @click="autoOpen = !autoOpen"
                  class="h-8 px-2.5 inline-flex items-center gap-1 rounded-lg text-[12px] text-[#4b4938] hover:bg-[#F5F1E3] transition"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="opacity-70">
                    <path d="M12 2v4M12 18v4M4.9 4.9l2.9 2.9M16.2 16.2l2.9 2.9M2 12h4M18 12h4M4.9 19.1l2.9-2.9M16.2 7.8l2.9-2.9" />
                  </svg>
                  {{ autoOptions[autoIdx] }}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[#a4a190]" stroke-linecap="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div
                  v-if="autoOpen"
                  class="absolute right-0 bottom-9 z-30 w-32 rounded-xl bg-white border border-[#EAE5D3] shadow-lg shadow-stone-900/5 p-1.5"
                >
                  <button
                    v-for="(o, i) in autoOptions"
                    :key="o"
                    type="button"
                    @click="((autoIdx = i), (autoOpen = false))"
                    class="w-full text-left px-2.5 py-1.5 rounded-lg text-[12.5px] transition"
                    :class="
                      i === autoIdx
                        ? 'bg-[#F2EDE1] text-[#2b2a22] font-medium'
                        : 'text-[#4b4938] hover:bg-[#F7F3E9]'
                    "
                  >
                    {{ o }}
                  </button>
                </div>
              </div>

              <button
                type="button"
                @click="toggleMic"
                class="h-8 w-8 grid place-items-center rounded-lg transition"
                :class="
                  micOn
                    ? 'bg-[#333228] text-[#F7F3E4]'
                    : 'text-[#5e5b4e] hover:bg-[#F5F1E3] hover:text-[#2b2a22]'
                "
                :title="micOn ? 'Stop voice' : 'Voice input'"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="2" width="6" height="12" rx="3" />
                  <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
                </svg>
              </button>

              <button
                type="button"
                @click="submit"
                :disabled="!draft.trim()"
                class="h-8 w-8 grid place-items-center rounded-lg transition"
                :class="
                  draft.trim()
                    ? 'bg-[#333228] text-[#F7F3E4] hover:bg-[#4a4838]'
                    : 'bg-[#F1EBD9] text-[#a4a190] cursor-not-allowed'
                "
                title="Send"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- 输入框下方提示 -->
        <p class="mt-2.5 text-center text-[11.5px] text-[#a4a190]">
          Choose workspace <span class="text-[#8a8872]">(optional)</span>
        </p>
      </div>
    </div>

    <!-- 右下角深色 ? 帮助按钮 -->
    <button
      type="button"
      class="absolute bottom-5 right-5 h-9 w-9 rounded-full bg-[#26251f] text-white grid place-items-center shadow-[0_6px_18px_rgba(20,20,15,0.25)] hover:bg-[#3a382d] transition text-[13px] font-semibold"
      title="Help"
    >
      ?
    </button>
  </section>
</template>
