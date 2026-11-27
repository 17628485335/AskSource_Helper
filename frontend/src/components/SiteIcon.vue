<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseHttpUrl } from '../utils/url'

const props = withDefaults(defineProps<{ url: string; size?: number }>(), { size: 16 })

const parsed = computed(() => parseHttpUrl(props.url))
const host = computed(() => parsed.value?.hostname.replace(/^www\./, '') || '')
const origin = computed(() => parsed.value?.origin || '')
const initial = computed(() => host.value.charAt(0).toUpperCase() || '?')

/** 依次尝试：Google 图标服务、DuckDuckGo 图标服务、站点自己的 favicon.ico */
const candidates = computed(() => {
  if (!host.value) return [] as string[]
  return [
    `https://www.google.com/s2/favicons?domain=${host.value}&sz=32`,
    `https://icons.duckduckgo.com/ip3/${host.value}.ico`,
    `${origin.value}/favicon.ico`,
  ]
})

const index = ref(0)
const failed = ref(false)
const current = computed(() => candidates.value[index.value] || '')
const sizeStyle = computed(() => ({ width: `${props.size}px`, height: `${props.size}px` }))

function onError() {
  if (index.value < candidates.value.length - 1) {
    index.value += 1
    return
  }
  failed.value = true
}
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-stone-100 text-[9px] leading-none text-stone-500"
    :style="sizeStyle"
  >
    {{ initial }}
    <img
      v-if="current && !failed"
      :key="current"
      :src="current"
      alt=""
      loading="lazy"
      class="absolute inset-0 h-full w-full object-contain"
      @error="onError"
    />
  </span>
</template>
