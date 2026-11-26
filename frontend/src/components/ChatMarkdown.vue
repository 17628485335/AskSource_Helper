<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MarkdownItVueStreaming } from 'markdown-it-vue3'
import 'markdown-it-vue3/dist/markdown-it-vue3.css'

const props = withDefaults(
  defineProps<{
    content: string
    final?: boolean
  }>(),
  { final: true },
)

/** 通知父组件打开右侧来源列表；参数 [n] 暂只用于未来按编号定位 */
const emit = defineEmits<{ (e: 'cite', index: number): void }>()

const root = ref<HTMLElement | null>(null)
let observer: MutationObserver | null = null
let decorating = false
let scheduled = false

function scheduleDecorate() {
  if (scheduled) return
  scheduled = true
  requestAnimationFrame(() => {
    scheduled = false
    decorate()
  })
}

function decorate() {
  const el = root.value
  if (!el || decorating) return
  decorating = true
  try {
    decorateTables(el)
    decorateCitations(el)
  } finally {
    decorating = false
  }
}

function decorateTables(el: HTMLElement) {
  el.querySelectorAll('table').forEach((table) => {
    if (table.parentElement?.classList.contains('md-table-wrap')) return
    const wrap = document.createElement('div')
    wrap.className = 'md-table-wrap'
    table.parentNode?.insertBefore(wrap, table)
    wrap.appendChild(table)
  })
}

function decorateCitations(el: HTMLElement) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (!parent) return NodeFilter.FILTER_REJECT
      // 代码块、链接、已处理的徽标里不要再替换 [n]
      if (parent.closest('pre, code, a, .cite-chip')) return NodeFilter.FILTER_REJECT
      if (!/\[\d{1,3}\]/.test(node.nodeValue || '')) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })

  const targets: Text[] = []
  while (walker.nextNode()) targets.push(walker.currentNode as Text)

  for (const node of targets) {
    const text = node.nodeValue || ''
    const frag = document.createDocumentFragment()
    let last = 0
    for (const match of text.matchAll(/\[(\d{1,3})\]/g)) {
      const at = match.index ?? 0
      if (at > last) frag.appendChild(document.createTextNode(text.slice(last, at)))
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'cite-chip'
      btn.dataset.cite = match[1]
      btn.textContent = match[1]
      btn.title = `查看来源 [${match[1]}]`
      frag.appendChild(btn)
      last = at + match[0].length
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)))
    node.parentNode?.replaceChild(frag, node)
  }
}

function onClick(e: MouseEvent) {
  const target = e.target as HTMLElement

  const chip = target.closest<HTMLElement>('[data-cite]')
  if (chip) {
    emit('cite', Number(chip.dataset.cite))
  }
}

onMounted(() => {
  observer = new MutationObserver(scheduleDecorate)
  if (root.value) {
    observer.observe(root.value, { childList: true, subtree: true, characterData: true })
  }
  scheduleDecorate()
})

watch(
  () => props.content,
  () => {
    void nextTick(scheduleDecorate)
  },
)

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="root" class="chat-markdown" @click="onClick">
    <MarkdownItVueStreaming :content="content" :streaming="!final" />
  </div>
</template>

<style scoped>
.chat-markdown {
  font-size: 14px;
  line-height: 1.75;
  color: #44403c;
  word-break: break-word;
}

.chat-markdown :deep(p) {
  margin: 0.7em 0;
}
.chat-markdown :deep(h1),
.chat-markdown :deep(h2),
.chat-markdown :deep(h3),
.chat-markdown :deep(h4) {
  margin: 0.9em 0 0.4em;
  font-weight: 650;
  line-height: 1.35;
  color: #292524;
}
.chat-markdown :deep(h1) {
  font-size: 1.28em;
}
.chat-markdown :deep(h2) {
  font-size: 1.16em;
}
.chat-markdown :deep(h3) {
  font-size: 1.08em;
}
.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  margin: 0.6em 0;
  padding-left: 1.5em;
}
.chat-markdown :deep(ul) {
  list-style: disc;
}
.chat-markdown :deep(ol) {
  list-style: decimal;
}
.chat-markdown :deep(li) {
  margin: 0.25em 0;
  padding-left: 0.15em;
}
.chat-markdown :deep(li::marker) {
  color: #a8a29e;
}
.chat-markdown :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.1em 0 0.1em 0.9em;
  border-left: 3px solid #e7e5e4;
  color: #78716c;
}
.chat-markdown :deep(a) {
  color: #57534e;
  text-decoration: underline;
  text-decoration-color: #d6d3d1;
  text-underline-offset: 3px;
}
.chat-markdown :deep(a:hover) {
  color: #292524;
  text-decoration-color: #a8a29e;
}
.chat-markdown :deep(strong) {
  font-weight: 650;
  color: #292524;
}
.chat-markdown :deep(:first-child) {
  margin-top: 0;
}
.chat-markdown :deep(:last-child) {
  margin-bottom: 0;
}

/* 代码块高亮与复制按钮交给 markdown-it-vue3 自带样式，这里不再覆盖 */
.chat-markdown :deep(.cite-chip) {
  font-family: inherit;
}

.chat-markdown :deep(.cite-chip) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 17px;
  height: 17px;
  margin: 0 1px;
  padding: 0 4px;
  border: 1px solid #e7e5e4;
  border-radius: 999px;
  background: #f5f5f4;
  color: #78716c;
  font-size: 10.5px;
  line-height: 1;
  vertical-align: 1px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.chat-markdown :deep(.cite-chip:hover) {
  border-color: #d6d3d1;
  background: #e7e5e4;
  color: #44403c;
}

.chat-markdown :deep(.md-table-wrap) {
  margin: 0.8em 0;
  border: 1px solid #e7e5e4;
  border-radius: 10px;
  overflow-x: auto;
}
.chat-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.chat-markdown :deep(th),
.chat-markdown :deep(td) {
  padding: 0.5em 0.7em;
  border-bottom: 1px solid #f0efed;
  text-align: left;
}
.chat-markdown :deep(th) {
  background: #fafaf9;
  font-weight: 600;
  color: #57534e;
}
.chat-markdown :deep(tr:nth-child(even) td) {
  background: #fafaf9;
}
</style>
