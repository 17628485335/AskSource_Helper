<script setup lang="ts">
import { ref } from 'vue'
import LeftRail from './components/LeftRail.vue'
import HomeStage from './components/HomeStage.vue'

/** 侧边栏折叠：展开约 20%，折叠为 64px 图标栏 */
const collapsed = ref(false)
</script>

<template>
  <div class="h-screen w-screen flex overflow-hidden bg-white">
    <!-- 左栏：约 20%，纵向渐变（折叠时 64px） -->
    <LeftRail
      v-model:collapsed="collapsed"
      class="transition-[width] duration-300 ease-in-out"
      :class="collapsed ? 'w-16 shrink-0' : 'w-[20%] min-w-[248px] max-w-[320px] shrink-0'"
    />
    <!-- 右栏：自适应剩余宽度，纯白主区 -->
    <HomeStage class="min-w-0 flex-1" />
  </div>
</template>
