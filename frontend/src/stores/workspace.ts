/**
 * 工作区状态存储（组合式单例）
 *
 * 持有工作区列表、当前选中项（localStorage 持久化）及当前工作区下的会话列表。
 * 只负责状态迁移与接口调用；渲染在 LeftRail，发消息时的归属由 HomeStage 读取。
 */

import { computed, ref } from 'vue'
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  updateWorkspace,
  type WorkspaceDto,
} from '../api/workspace'
import { listSessions, type SessionDto } from '../api/session'

const ACTIVE_KEY = 'asksource_workspace_id'

const workspaces = ref<WorkspaceDto[]>([])
/** 当前选中工作区下的会话（左侧栏「工作区」区块展示，点击可恢复对话） */
const sessions = ref<SessionDto[]>([])
const loading = ref(false)
/** 最近一次写操作的失败原因（如数量上限、重名约束），由 UI 就近展示 */
const lastError = ref('')

function readStoredId(): number | null {
  const n = Number(localStorage.getItem(ACTIVE_KEY))
  return Number.isFinite(n) && n > 0 ? n : null
}

const activeId = ref<number | null>(readStoredId())
const activeWorkspace = computed(() =>
  workspaces.value.find((w) => w.id === activeId.value) ?? null,
)

/** 切换选中工作区并重新拉取其会话列表 */
function select(id: number | null): void {
  activeId.value = id
  if (id == null) localStorage.removeItem(ACTIVE_KEY)
  else localStorage.setItem(ACTIVE_KEY, String(id))
  void loadSessions()
}

async function loadSessions(): Promise<void> {
  if (!activeId.value) {
    sessions.value = []
    return
  }
  try {
    const page = await listSessions({ workspace_id: activeId.value, limit: 30 })
    sessions.value = page.items
  } catch {
    sessions.value = []
  }
}

/** 从后端加载工作区（需登录）；本地记录的选中 id 已失效时回落到第一个 */
async function load(): Promise<void> {
  loading.value = true
  try {
    workspaces.value = await listWorkspaces()
    if (!workspaces.value.some((w) => w.id === activeId.value)) {
      select(workspaces.value[0]?.id ?? null)
    } else {
      await loadSessions()
    }
  } catch {
    // 未登录或后端不可用时保持空态，不阻断界面
  } finally {
    loading.value = false
  }
}

async function create(name: string): Promise<WorkspaceDto | null> {
  lastError.value = ''
  try {
    const ws = await createWorkspace({ name })
    workspaces.value.push(ws)
    return ws
  } catch (e) {
    lastError.value = e instanceof Error ? e.message : '创建失败'
    return null
  }
}

async function rename(id: number, name: string): Promise<boolean> {
  lastError.value = ''
  try {
    const ws = await updateWorkspace(id, { name })
    const idx = workspaces.value.findIndex((w) => w.id === id)
    if (idx !== -1) workspaces.value[idx] = ws
    return true
  } catch (e) {
    lastError.value = e instanceof Error ? e.message : '重命名失败'
    return false
  }
}

/** 删除工作区；选中的是被删区时回落到剩余的第一个 */
async function remove(id: number): Promise<boolean> {
  lastError.value = ''
  try {
    await deleteWorkspace(id)
    workspaces.value = workspaces.value.filter((w) => w.id !== id)
    if (activeId.value === id) select(workspaces.value[0]?.id ?? null)
    return true
  } catch (e) {
    lastError.value = e instanceof Error ? e.message : '删除失败'
    return false
  }
}

/** 登出时清本地状态（服务端数据不动） */
function clear(): void {
  workspaces.value = []
  sessions.value = []
  lastError.value = ''
}

export function useWorkspace() {
  return {
    workspaces,
    sessions,
    activeId,
    activeWorkspace,
    loading,
    lastError,
    load,
    select,
    loadSessions,
    create,
    rename,
    remove,
    clear,
  }
}
