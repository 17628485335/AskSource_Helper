import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    proxy: {
      // 开发环境把 /auth/* 代理到独立的 auth 微服务（默认 8001），规避跨域
      '/auth': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      // 设置类接口（/settings/model-providers 等）同样代理到后端
      '/settings': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 会话与流式对话接口（/sessions、/chat）
      '/sessions': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 工作区接口（/workspaces）
      '/workspaces': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Agent 定义与提示词版本接口（/agents）
      '/agents': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 上下文分段管理与内容生成接口（/context）
      '/context': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
