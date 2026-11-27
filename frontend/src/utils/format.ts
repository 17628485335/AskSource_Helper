/** 纯展示格式化：与业务状态无关，供各组件复用 */

/** 完整到秒的本地时间（年-月-日 时:分:秒）；非法日期返回空串 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 列表里的日期：同年省略年份，跨年补上；非法日期返回空串 */
export function formatDay(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const sameYear = d.getFullYear() === today.getFullYear()
  const md = `${d.getMonth() + 1}月${d.getDate()}日`
  return sameYear ? md : `${d.getFullYear()}年${md}`
}

/** 上下文窗口的简短展示，统一用 K：200000 → 200K，1048576(1M) → 1000K */
export function formatTokenCompact(tokens?: number): string {
  if (!tokens || tokens <= 0) return ''
  if (tokens >= 1024 * 1024) return `${Math.round(tokens / (1024 * 1024) * 1000)}K`
  return `${Math.round(tokens / 1000)}K`
}
