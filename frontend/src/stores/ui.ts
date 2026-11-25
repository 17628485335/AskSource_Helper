import { ref } from 'vue'

/**
 * 右侧主区域视图态（仅首页展示与新对话画布二选一；会话中由 hasConversation 接管）
 * - 'home'：品牌首页（logo + slogan + 热力图），点左上角 A logo 进入
 * - 'chat'：ChatGPT 式空白画布 + 问候语，新对话 / 打开历史会话时回到此态
 */
export type StageView = 'home' | 'chat'

const view = ref<StageView>('chat')

export function useUi() {
  function goHome() {
    view.value = 'home'
  }
  function goChat() {
    view.value = 'chat'
  }
  return { view, goHome, goChat }
}
