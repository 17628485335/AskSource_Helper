/** URL 解析与安全校验：外部搜索接口返回的 url 会进 href，必须先拦掉 javascript: 等协议 */

/** 只放行 http(s)；解析失败或协议不合法返回 null */
export function parseHttpUrl(url: string): URL | null {
  try {
    const u = new URL(url)
    return /^https?:$/.test(u.protocol) ? u : null
  } catch {
    return null
  }
}

/** 展示用域名，去掉 www.；不校验协议，仅用于文案（进 href 前须过 safeHttpUrl） */
export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** 进 href / 图标 URL 前的安全放行：只保留 http(s) 原串 */
export function safeHttpUrl(url: string): string {
  return /^https?:\/\//i.test(url) ? url : ''
}
