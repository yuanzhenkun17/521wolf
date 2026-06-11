<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TaskArtifactPanel from '../components/tasks/TaskArtifactPanel.vue'
import { createTaskService } from '../services/taskApi'
import type { TaskActionResponse, TaskEventRow, TaskQueueRow } from '../types/task'

type StatusFilterKey = 'all' | 'active' | 'queued' | 'running' | 'terminal' | 'failed'

const STATUS_FILTERS: Array<{
  key: StatusFilterKey
  label: string
  caption: string
  statuses: string[]
}> = [
  { key: 'active', label: '活跃', caption: 'queued / running', statuses: ['queued', 'running'] },
  { key: 'all', label: '全部', caption: '最近任务', statuses: [] },
  { key: 'queued', label: '排队', caption: '等待 worker', statuses: ['queued'] },
  { key: 'running', label: '运行中', caption: 'lease 有效', statuses: ['running'] },
  { key: 'terminal', label: '已结束', caption: '成功 / 取消 / 中断', statuses: ['succeeded', 'cancelled', 'interrupted'] },
  { key: 'failed', label: '失败', caption: '需要检查', statuses: ['failed'] }
]

const taskKindLabels: Record<string, string> = {
  benchmark_batch: 'Benchmark',
  evolution_run: 'Evolution Run',
  evolution_batch: 'Evolution Batch',
  langfuse_verification: 'Langfuse 验证',
  langfuse_annotation_export: '标注导出',
  langfuse_link_manifest: 'Link Manifest'
}

const route = useRoute()
const router = useRouter()
const taskService = createTaskService()

const tasks = ref<TaskQueueRow[]>([])
const selectedTask = ref<TaskQueueRow | null>(null)
const events = ref<TaskEventRow[]>([])
const selectedTaskId = ref(routeQueryText(route.query.task_id))
const activeFilter = ref<StatusFilterKey>('active')
const searchText = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const eventsLoading = ref(false)
const error = ref('')
const detailError = ref('')
const eventsError = ref('')
const refreshedAt = ref('')
const eventsExpanded = ref(false)

const selectedFilter = computed(() =>
  STATUS_FILTERS.find((item) => item.key === activeFilter.value) || STATUS_FILTERS[0]
)
const selectedStatuses = computed(() => new Set(selectedFilter.value.statuses))
const visibleTasks = computed(() => {
  const statuses = selectedStatuses.value
  const query = searchText.value.trim().toLowerCase()
  return tasks.value
    .filter((task) => !statuses.size || statuses.has(String(task.status || '').toLowerCase()))
    .filter((task) => {
      if (!query) return true
      return [
        task.task_id,
        task.kind,
        task.status,
        task.statusLabel,
        task.stageLabel,
        task.source,
        task.metadata?.domain_status
      ].some((value) => String(value || '').toLowerCase().includes(query))
    })
    .sort((a, b) => taskTimeValue(b) - taskTimeValue(a))
})
const selectedListTask = computed(() =>
  tasks.value.find((task) => task.task_id === selectedTaskId.value || task.id === selectedTaskId.value) || null
)
const activeTask = computed(() => selectedTask.value || selectedListTask.value)
const activeTaskProgressPercent = computed(() => normalizedPercent(activeTask.value?.progressPercent))
const statusCounts = computed(() => {
  const counts: Record<string, number> = { all: tasks.value.length, active: 0, terminal: 0, failed: 0 }
  tasks.value.forEach((task) => {
    const status = String(task.status || '').toLowerCase()
    counts[status] = (counts[status] || 0) + 1
    if (task.isActive) counts.active += 1
    if (task.isTerminal) counts.terminal += 1
    if (status === 'failed') counts.failed += 1
  })
  return counts
})
const taskMetaRows = computed(() => [
  { key: 'total', label: '任务', value: tasks.value.length || '0' },
  { key: 'active', label: '活跃', value: statusCounts.value.active || '0', tone: statusCounts.value.active ? 'neutral' : 'muted' },
  { key: 'filter', label: '筛选', value: selectedFilter.value.label },
  { key: 'selected', label: '选中', value: activeTask.value?.statusLabel || '无' }
])
const contextRows = computed(() => {
  const task = activeTask.value
  if (!task) return []
  return [
    { key: 'kind', label: '类型', value: taskKindLabel(task.kind) },
    { key: 'status', label: '状态', value: task.statusLabel },
    { key: 'stage', label: '阶段', value: task.stageLabel },
    { key: 'progress', label: '进度', value: task.progressLabel },
    { key: 'attempt', label: '尝试', value: `${task.attempt} / ${task.max_attempts}` },
    { key: 'source', label: '来源', value: task.source || '未标记' },
    { key: 'queued', label: '入队', value: formatDateTime(task.queued_at) || '未记录' },
    { key: 'updated', label: '更新', value: formatDateTime(task.updated_at) || '未记录' },
    { key: 'finished', label: '结束', value: formatDateTime(task.finished_at) || '未结束' }
  ]
})
const eventRows = computed(() =>
  events.value.map((event, index) => ({
    key: eventKey(event, index),
    type: eventType(event),
    time: eventTime(event),
    payload: eventPayload(event)
  }))
)

watch(
  () => route.query.task_id,
  (value) => {
    const next = routeQueryText(value)
    if (next !== selectedTaskId.value) {
      selectedTaskId.value = next
      void loadSelectedTask()
    }
  }
)

watch(visibleTasks, (rows) => {
  if (selectedTaskId.value && rows.some((task) => task.task_id === selectedTaskId.value || task.id === selectedTaskId.value)) return
  if (!selectedTaskId.value && rows[0]) {
    selectTask(rows[0])
  }
})

onMounted(() => {
  void refreshAll()
})

function routeQueryText(value: unknown): string {
  if (Array.isArray(value)) return routeQueryText(value[0])
  return String(value || '').trim()
}

function taskTimeValue(task: TaskQueueRow): number {
  const raw = task.updated_at || task.started_at || task.queued_at || task.finished_at
  const time = raw ? new Date(raw).getTime() : 0
  return Number.isFinite(time) ? time : 0
}

function taskKindLabel(kind: unknown): string {
  const key = String(kind || '').trim()
  return taskKindLabels[key] || key || 'task'
}

function formatDateTime(value: unknown): string {
  const text = String(value || '').trim()
  if (!text) return ''
  const date = new Date(text)
  if (!Number.isFinite(date.getTime())) return text
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

function shortTaskId(value: unknown): string {
  const text = String(value || '').trim()
  if (!text) return '—'
  return text.length > 22 ? `${text.slice(0, 22)}...` : text
}

function statusCountFor(filter: (typeof STATUS_FILTERS)[number]): number {
  if (filter.key === 'all') return statusCounts.value.all || 0
  if (filter.key === 'active') return statusCounts.value.active || 0
  if (filter.key === 'terminal') return statusCounts.value.terminal || 0
  if (filter.key === 'failed') return statusCounts.value.failed || 0
  return filter.statuses.reduce((total, status) => total + (statusCounts.value[status] || 0), 0)
}

function normalizedPercent(value: unknown): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function selectFilter(filter: StatusFilterKey) {
  activeFilter.value = filter
}

function selectTask(task: TaskQueueRow | null) {
  const nextId = task?.task_id || task?.id || ''
  selectedTaskId.value = nextId
  selectedTask.value = task
  events.value = []
  eventsExpanded.value = false
  detailError.value = ''
  eventsError.value = ''
  const query = { ...route.query }
  if (nextId) query.task_id = nextId
  else delete query.task_id
  void router.replace({ path: route.path, query }).catch(() => {})
  void loadSelectedTask()
}

async function refreshAll() {
  loading.value = true
  error.value = ''
  try {
    const response = await taskService.list({ limit: 200 })
    tasks.value = response.tasks
    refreshedAt.value = new Date().toISOString()
    if (!selectedTaskId.value && visibleTasks.value[0]) {
      selectTask(visibleTasks.value[0])
    } else {
      await loadSelectedTask()
    }
  } catch (err) {
    error.value = errorMessage(err, '任务队列读取失败')
  } finally {
    loading.value = false
  }
}

async function loadSelectedTask() {
  const taskId = selectedTaskId.value
  selectedTask.value = selectedListTask.value
  events.value = []
  detailError.value = ''
  eventsError.value = ''
  if (!taskId) return
  detailLoading.value = true
  eventsLoading.value = true
  try {
    const [taskResult, eventResult] = await Promise.allSettled([
      taskService.get(taskId),
      taskService.events(taskId, 0)
    ])
    if (taskResult.status === 'fulfilled') {
      selectedTask.value = taskResult.value
    } else {
      detailError.value = errorMessage(taskResult.reason, '任务详情读取失败')
    }
    if (eventResult.status === 'fulfilled') {
      events.value = eventResult.value.events
    } else {
      eventsError.value = errorMessage(eventResult.reason, '任务事件读取失败')
    }
  } finally {
    detailLoading.value = false
    eventsLoading.value = false
  }
}

function handleTaskAction(_response: TaskActionResponse) {
  void refreshAll()
}

function errorMessage(err: unknown, fallback: string): string {
  const source = err as { status?: number; message?: string }
  if (source?.status === 404) return '任务不存在或已被清理'
  return String(source?.message || fallback)
}

function eventKey(event: TaskEventRow, index: number): string {
  return String(event.event_id ?? event.id ?? `${eventType(event)}-${index}`)
}

function eventType(event: TaskEventRow): string {
  return String(event.event_type || event.event || event.type || 'event')
}

function eventTime(event: TaskEventRow): string {
  return formatDateTime(event.created_at)
}

function eventPayload(event: TaskEventRow): string {
  const payload = event.payload ?? event
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload || '')
  }
}
</script>

<template>
  <section class="tasks-page" aria-label="任务中心">
    <section class="tasks-shell parchment-logbook">
      <aside class="tasks-control-rail" aria-label="任务筛选">
        <header class="tasks-rail-header">
          <span>任务上下文</span>
          <strong>{{ visibleTasks.length }} / {{ tasks.length }}</strong>
        </header>

        <div class="tasks-filter-panel">
          <div class="tasks-filter-head">
            <span class="tasks-rail-label">状态筛选</span>
            <p v-if="refreshedAt" class="task-refresh-note">{{ formatDateTime(refreshedAt) }}</p>
          </div>
          <label class="task-search">
            <input v-model="searchText" type="search" placeholder="搜索 task / kind / stage" aria-label="搜索任务" />
          </label>
          <div class="task-filter-list">
            <button
              v-for="filter in STATUS_FILTERS"
              :key="filter.key"
              type="button"
              :data-filter="filter.key"
              :class="['task-filter-chip', { selected: activeFilter === filter.key }]"
              @click="selectFilter(filter.key)"
            >
              <span>
                <b>{{ filter.label }}</b>
                <small>{{ filter.caption }}</small>
              </span>
              <em>{{ statusCountFor(filter) }}</em>
            </button>
          </div>
        </div>
      </aside>

      <main class="tasks-detail-panel">
        <header class="tasks-command-bar">
          <div class="tasks-command-title">
            <h2>任务工作台</h2>
          </div>
          <div class="tasks-command-metrics" aria-label="任务状态条">
            <span v-for="item in taskMetaRows" :key="item.key">
              <small>{{ item.label }}：</small>
              <b :title="String(item.value ?? '')">{{ item.value }}</b>
            </span>
          </div>
          <div class="tasks-command-actions">
            <button type="button" class="tasks-refresh-button" :disabled="loading" @click="refreshAll">
              <span aria-hidden="true">&#8635;</span> {{ loading ? '刷新中' : '刷新' }}
            </button>
          </div>
        </header>

        <section class="tasks-main-pane">
          <div class="tasks-scroll">
            <div v-if="error" class="task-warning">{{ error }}</div>

            <section class="tasks-card task-list-panel" aria-label="任务列表">
              <header>
                <div>
                  <small>任务列表</small>
                  <h2>{{ visibleTasks.length }} 个任务</h2>
                </div>
                <b>{{ selectedFilter.label }}</b>
              </header>
              <div class="task-table">
                <button
                  v-for="task in visibleTasks"
                  :key="task.task_id"
                  type="button"
                  :class="['task-row', { selected: selectedTaskId === task.task_id || selectedTaskId === task.id }]"
                  :data-status="task.status"
                  @click="selectTask(task)"
                >
                  <span class="task-status-dot" aria-hidden="true"></span>
                  <span class="task-main-cell">
                    <b :title="task.task_id">{{ shortTaskId(task.task_id) }}</b>
                    <small :title="task.kind">{{ taskKindLabel(task.kind) }} / {{ task.stageLabel }}</small>
                  </span>
                  <span class="task-progress-cell">
                    <b>{{ task.statusLabel }}</b>
                    <i aria-hidden="true"><em :style="{ width: `${normalizedPercent(task.progressPercent)}%` }"></em></i>
                  </span>
                  <span class="task-time-cell">
                    <b>{{ task.progressLabel }}</b>
                    <small>{{ formatDateTime(task.updated_at || task.queued_at) || '未记录' }}</small>
                  </span>
                </button>
                <div v-if="!visibleTasks.length && !loading" class="task-empty">当前筛选无任务。</div>
                <div v-if="loading" class="task-empty">正在读取任务队列。</div>
              </div>
            </section>

            <section
              :class="['tasks-card', 'task-events-panel', { expanded: eventsExpanded }]"
              aria-label="任务事件时间线"
            >
              <header class="task-events-header">
                <button
                  type="button"
                  class="task-events-toggle"
                  :aria-expanded="eventsExpanded"
                  aria-controls="task-events-content"
                  @click="eventsExpanded = !eventsExpanded"
                >
                  <span>
                    <small>事件时间线</small>
                    <strong>{{ eventRows.length }} 条事件</strong>
                  </span>
                  <i aria-hidden="true"></i>
                </button>
                <button type="button" class="tasks-card-action" :disabled="!selectedTaskId || eventsLoading" @click="loadSelectedTask">
                  {{ eventsLoading ? '读取中' : '刷新事件' }}
                </button>
              </header>
              <div v-show="eventsExpanded" id="task-events-content" class="task-events-content">
                <p v-if="eventsError" class="task-warning">{{ eventsError }}</p>
                <ol v-else-if="eventRows.length" class="task-event-list">
                  <li v-for="event in eventRows" :key="event.key">
                    <span>
                      <b>{{ event.type }}</b>
                      <small>{{ event.time || event.key }}</small>
                    </span>
                    <pre>{{ event.payload }}</pre>
                  </li>
                </ol>
                <div v-else class="task-empty">
                  {{ selectedTaskId ? '暂无任务事件。' : '选择任务后显示事件。' }}
                </div>
              </div>
            </section>
          </div>
        </section>
      </main>

      <aside class="tasks-context-rail" aria-label="任务详情" data-tasks-context-rail>
        <div class="tasks-context-scroll">
          <header class="tasks-context-head">
            <span>
              <small>当前任务</small>
              <strong :title="activeTask?.task_id || activeTask?.id || ''">
                {{ shortTaskId(activeTask?.task_id || activeTask?.id) }}
              </strong>
            </span>
            <b>{{ activeTask?.statusLabel || '—' }}</b>
          </header>

          <section class="tasks-context-section">
            <h3>任务摘要</h3>
            <p v-if="detailLoading" class="tasks-context-empty">正在读取任务详情。</p>
            <p v-else-if="detailError" class="task-warning">{{ detailError }}</p>
            <template v-else-if="activeTask">
              <div class="tasks-context-run-id">
                <small>task_id</small>
                <code>{{ activeTask.task_id || activeTask.id }}</code>
              </div>
              <div class="tasks-context-progress">
                <span>
                  <b>{{ activeTaskProgressPercent }}%</b>
                  <small>{{ activeTask.progressLabel || '等待' }}</small>
                </span>
                <i aria-hidden="true">
                  <em :style="{ width: `${activeTaskProgressPercent}%` }"></em>
                </i>
              </div>
              <div class="tasks-context-kpis">
                <span v-for="item in contextRows" :key="item.key" :class="{ wide: item.key === 'source' }">
                  <small>{{ item.label }}</small>
                  <b :title="String(item.value ?? '')">{{ item.value }}</b>
                </span>
              </div>
            </template>
            <p v-else class="tasks-context-empty">未选择任务。</p>
          </section>

          <TaskArtifactPanel
            :task-id="selectedTaskId"
            class="tasks-artifact-panel"
            title="任务产物与控制"
            eyebrow="ArtifactStore"
            show-actions
            @action-complete="handleTaskAction"
          />
        </div>
      </aside>
    </section>
  </section>
</template>

<style scoped>
.tasks-page {
  --logbook-bg: #f2dfae;
  --logbook-bg-texture:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--logbook-bg);
  --logbook-surface: rgba(255, 252, 245, 0.52);
  --logbook-panel: rgba(255, 252, 245, 0.68);
  --logbook-panel-solid: rgba(255, 250, 240, 0.76);
  --logbook-panel-soft: rgba(255, 242, 210, 0.42);
  --logbook-border: rgba(139, 94, 52, 0.15);
  --logbook-border-strong: rgba(90, 51, 25, 0.34);
  --logbook-text: #3a2a18;
  --logbook-muted: #8b6b4a;
  --logbook-accent: #8b5e34;
  --logbook-accent-strong: #5a3319;
  --logbook-input-bg: rgba(255, 255, 250, 0.58);
  --logbook-input-border: rgba(139, 94, 52, 0.2);
  --logbook-hover: rgba(139, 94, 52, 0.06);
  --logbook-active-bg: rgba(139, 94, 52, 0.1);
  --logbook-danger: #993026;
  --logbook-warning: #76510e;
  --evo-bg: var(--logbook-bg);
  --evo-bg-texture: var(--logbook-bg-texture);
  --evo-surface: var(--logbook-surface);
  --evo-border: var(--logbook-border);
  --evo-border-strong: var(--logbook-border-strong);
  --evo-text: var(--logbook-text);
  --evo-text-secondary: var(--logbook-muted);
  --evo-accent: var(--logbook-accent);
  --evo-accent-strong: var(--logbook-accent-strong);
  --evo-input-bg: var(--logbook-input-bg);
  --evo-input-border: var(--logbook-input-border);
  --evo-hover: var(--logbook-hover);
  --evo-active-bg: var(--logbook-active-bg);
  --evo-card-bg: var(--logbook-surface);
  --evo-code-bg: #2d2218;
  --evo-success: #6a5f23;
  --evo-danger: var(--logbook-danger);
  --evo-warning: var(--logbook-warning);
  --tasks-bg: var(--evo-bg);
  --tasks-bg-texture: var(--evo-bg-texture);
  --tasks-surface: var(--evo-surface);
  --tasks-border: var(--evo-border);
  --tasks-border-strong: var(--evo-border-strong);
  --tasks-text: var(--evo-text);
  --tasks-muted: var(--evo-text-secondary);
  --tasks-accent: var(--evo-accent);
  --tasks-accent-strong: var(--evo-accent-strong);
  --tasks-input-bg: var(--evo-input-bg);
  --tasks-input-border: var(--evo-input-border);
  --tasks-hover: var(--evo-hover);
  --tasks-active-bg: var(--evo-active-bg);
  --tasks-danger: var(--evo-danger);
  --tasks-font: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
  position: fixed;
  z-index: 11;
  top: 72px;
  right: 0;
  bottom: 0;
  left: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: transparent;
  color: var(--tasks-text);
  font-family: var(--tasks-font);
  -webkit-font-smoothing: auto;
  text-rendering: auto;
}

.tasks-page *:not(svg):not(svg *) {
  box-sizing: border-box;
  font-family: var(--tasks-font);
}

.tasks-page button,
.tasks-page input,
.tasks-page code,
.tasks-page pre {
  font-family: var(--tasks-font);
}

.tasks-shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr) 292px;
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "rail command context"
    "rail pane context";
  column-gap: 18px;
  row-gap: 0;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  padding: 26px;
}

.tasks-shell.parchment-logbook {
  grid-template-columns: 248px minmax(0, 1fr) 292px;
  background: var(--tasks-bg-texture);
}

.tasks-detail-panel {
  display: contents;
}

.tasks-control-rail,
.tasks-main-pane,
.tasks-context-rail,
.tasks-scroll,
.tasks-context-scroll,
.tasks-card,
.task-table,
.task-row {
  min-width: 0;
  min-height: 0;
}

.tasks-command-bar {
  grid-area: command;
  display: grid;
  grid-template-columns: minmax(108px, 0.32fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  padding: 18px 20px 16px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background:
    linear-gradient(135deg, rgba(58, 42, 24, 0.96), rgba(90, 51, 25, 0.9)),
    repeating-linear-gradient(90deg, rgba(232, 196, 132, 0.08) 0 1px, transparent 1px 18px);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.1);
}

.tasks-command-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: end;
  gap: 4px;
  min-width: 0;
}

.tasks-command-title h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #fff4d9;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-command-metrics {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  min-width: 0;
  overflow: hidden;
}

.tasks-command-metrics span {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  flex: 0 0 92px;
  max-width: 128px;
  min-width: 0;
  overflow: hidden;
}

.tasks-command-metrics span:nth-child(4) {
  flex: 1 1 112px;
  max-width: 160px;
}

.tasks-command-metrics small {
  flex: 0 0 auto;
  color: rgba(232, 210, 170, 0.68);
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
}

.tasks-command-metrics b {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 14px;
  font-weight: 800;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-command-actions {
  display: flex;
  justify-content: flex-end;
}

.tasks-refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 92px;
  height: 42px;
  padding: 0 15px;
  border: 1px solid rgba(232, 196, 132, 0.24);
  border-radius: 7px;
  background: #e8c484;
  color: #2d1e10;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(18, 10, 5, 0.18);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  white-space: nowrap;
}

.tasks-refresh-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(18, 10, 5, 0.22);
}

.tasks-refresh-button:disabled,
.tasks-card-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.task-filter-chip,
.tasks-refresh-button {
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.42);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.task-filter-chip:hover,
.tasks-refresh-button:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: var(--tasks-text);
  background: rgba(255, 245, 214, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.82);
  transform: none;
}

.task-filter-chip.selected {
  border-color: rgba(93, 48, 17, 0.45);
  color: var(--tasks-text);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.tasks-control-rail {
  grid-area: rail;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding: 0 14px 0 0;
  border-right: 1px solid rgba(91, 47, 18, 0.2);
  background: transparent;
}

.tasks-rail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--tasks-border);
}

.tasks-rail-header span {
  min-width: 0;
  overflow: hidden;
  color: var(--tasks-text);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-rail-header strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  margin-left: auto;
  padding: 0 7px;
  border-radius: 11px;
  background: var(--tasks-active-bg);
  color: var(--tasks-accent);
  font-size: 12px;
  font-weight: 800;
}

.task-filter-chip small,
.task-search span,
.task-refresh-note,
.task-row small,
.tasks-card small,
.tasks-context-head small,
.tasks-context-section h3,
.tasks-context-kpis small,
.tasks-context-run-id small,
.tasks-context-progress small {
  color: var(--tasks-muted);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0;
  line-height: 1.1;
}

.task-filter-chip b,
.task-row b,
.tasks-card header b,
.tasks-context-head strong,
.tasks-context-head b,
.tasks-context-kpis b,
.tasks-context-run-id code {
  min-width: 0;
  overflow: hidden;
  color: var(--tasks-text);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-filter-panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
}

.tasks-filter-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.tasks-rail-label {
  flex: 0 0 auto;
  color: var(--tasks-accent);
  font-size: 12px;
  font-weight: 800;
}

.task-filter-list {
  display: grid;
  grid-template-columns: 1fr;
  grid-auto-rows: max-content;
  gap: 7px;
  align-content: start;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.28) transparent;
}

.task-filter-chip {
  --task-filter-color: var(--tasks-accent);
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  position: relative;
  width: 100%;
  min-height: 36px;
  padding: 0 10px 0 12px;
  color: var(--tasks-muted);
  font-size: 12px;
  font-weight: 800;
  text-align: left;
  cursor: pointer;
}

.task-filter-chip::before {
  content: "";
  width: 16px;
  height: 16px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 5px;
  background:
    radial-gradient(circle at 50% 50%, rgba(255, 252, 228, 0.92) 0 2px, transparent 2px),
    var(--task-filter-color);
  box-shadow:
    inset 0 1px 0 rgba(255, 252, 228, 0.58),
    0 1px 2px rgba(93, 48, 17, 0.12);
}

.task-filter-chip::after {
  content: "";
  position: absolute;
  top: 7px;
  bottom: 7px;
  left: 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--task-filter-color);
  opacity: 0.62;
}

.task-filter-chip[data-filter="active"],
.task-filter-chip[data-filter="running"] {
  --task-filter-color: #6a7a2c;
}

.task-filter-chip[data-filter="queued"] {
  --task-filter-color: #b9852f;
}

.task-filter-chip[data-filter="terminal"] {
  --task-filter-color: #7a6047;
}

.task-filter-chip[data-filter="failed"] {
  --task-filter-color: var(--tasks-danger);
}

.task-filter-chip[data-filter="all"] {
  --task-filter-color: var(--tasks-accent);
}

.task-filter-chip span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.task-filter-chip em {
  flex: 0 0 auto;
  min-width: max-content;
  color: currentColor;
  font-size: 10px;
  font-style: normal;
  font-weight: 750;
  opacity: 0.72;
  white-space: nowrap;
}

.task-search {
  display: block;
  min-width: 0;
}

.task-search input {
  width: 100%;
  min-width: 0;
  height: 30px;
  padding: 0 2px;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.16);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.12);
  box-shadow: none;
  color: var(--tasks-text);
  font-size: 12px;
  font-weight: 850;
  outline: none;
}

.task-search input::placeholder {
  color: rgba(74, 37, 15, 0.45);
}

.task-search:focus-within input {
  border-bottom-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 252, 245, 0.28);
}

.task-refresh-note {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 10px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-main-pane {
  grid-area: pane;
  align-self: start;
  max-height: calc(100vh - 245px);
  overflow: hidden;
  border: 1px solid var(--tasks-border);
  border-top: none;
  border-radius: 0 0 8px 8px;
  background: rgba(255, 252, 245, 0.24);
}

.tasks-scroll {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: auto;
  min-height: 0;
  max-height: calc(100vh - 245px);
  overflow-y: auto;
  padding: 16px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.tasks-scroll::-webkit-scrollbar,
.tasks-context-scroll::-webkit-scrollbar {
  width: 6px;
}

.tasks-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.tasks-scroll::-webkit-scrollbar-thumb,
.tasks-context-scroll::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: rgba(139, 94, 52, 0.18);
}

.tasks-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(139, 94, 52, 0.25);
}

.tasks-card {
  display: grid;
  align-content: start;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(93, 48, 17, 0.16);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.36), rgba(255, 239, 194, 0.18)),
    rgba(255, 252, 245, 0.24);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.48);
}

.tasks-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  min-height: 38px;
  margin: -2px 0 0;
  padding: 0 0 10px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.14);
}

.tasks-card > header > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.tasks-card h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tasks-card header b {
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 239, 194, 0.38);
  color: rgba(74, 37, 15, 0.72);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.2;
}

.tasks-card-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.42);
  color: rgba(59, 28, 9, 0.78);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

.task-events-panel {
  gap: 0;
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  overflow: hidden;
  padding-block: 10px;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.74), rgba(255, 239, 194, 0.42)),
    var(--tasks-panel-solid);
}

.task-events-panel.expanded {
  gap: 12px;
  padding-block: 14px;
}

.task-events-panel > .task-events-header {
  min-height: 34px;
  margin: 0;
  padding: 0;
  border-bottom: 0;
}

.task-events-panel.expanded > .task-events-header {
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.14);
}

.task-events-toggle {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 0;
  border: 0;
  color: var(--tasks-text);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.task-events-toggle span {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.task-events-toggle small {
  color: var(--tasks-muted);
  font-size: 11px;
  font-weight: 850;
}

.task-events-toggle strong {
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
}

.task-events-toggle i {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  margin-right: 3px;
  border-right: 2px solid rgba(74, 37, 15, 0.66);
  border-bottom: 2px solid rgba(74, 37, 15, 0.66);
  transform: rotate(45deg) translateY(-2px);
  transition: transform 0.16s ease;
}

.task-events-toggle[aria-expanded="true"] i {
  transform: rotate(225deg) translate(-2px, -2px);
}

.task-events-content {
  display: grid;
  gap: 8px;
  min-width: 0;
  max-height: clamp(220px, 42vh, 430px);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.task-table {
  display: grid;
  align-content: start;
  gap: 7px;
}

.task-row {
  display: grid;
  grid-template-columns: 10px minmax(0, 1.3fr) minmax(118px, 0.8fr) minmax(128px, 0.75fr);
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 50px;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.5);
  color: var(--tasks-text);
  text-align: left;
  cursor: pointer;
}

.task-row:hover {
  border-color: rgba(93, 48, 17, 0.26);
  background: rgba(255, 245, 214, 0.54);
}

.task-row.selected {
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.36);
}

.task-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--tasks-muted);
}

.task-row[data-status="queued"] .task-status-dot,
.task-row[data-status="running"] .task-status-dot {
  background: var(--evo-success);
}

.task-row[data-status="failed"] .task-status-dot,
.task-row[data-status="interrupted"] .task-status-dot {
  background: var(--tasks-danger);
}

.task-main-cell,
.task-progress-cell,
.task-time-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.task-row b {
  color: #3b1c09;
  font-weight: 900;
}

.task-progress-cell i {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.13);
}

.task-progress-cell em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--tasks-accent);
}

.task-event-list {
  display: grid;
  gap: 8px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-event-list li {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding: 9px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.5);
}

.task-event-list li span {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.task-event-list pre {
  max-height: 180px;
  min-width: 0;
  overflow: auto;
  margin: 0;
  padding: 8px;
  border-radius: 7px;
  background: var(--evo-code-bg);
  color: #f6e6c8;
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.tasks-context-rail {
  grid-area: context;
  max-width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  padding-left: 16px;
  border-left: 1px solid rgba(93, 48, 17, 0.2);
}

.tasks-context-scroll {
  display: grid;
  align-content: start;
  gap: 12px;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.3) transparent;
}

.tasks-context-head,
.tasks-context-section,
.tasks-context-scroll :deep(.task-artifact-panel) {
  max-width: 100%;
  min-width: 0;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.28), rgba(255, 239, 194, 0.14)),
    rgba(255, 252, 245, 0.2);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.46);
}

.tasks-context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
}

.tasks-context-head span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.tasks-context-section {
  display: grid;
  gap: 10px;
  padding: 11px 12px 12px;
}

.tasks-context-section h3 {
  margin: 0;
  padding-bottom: 7px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  color: #3b1c09;
  font-size: 13px;
  font-weight: 950;
}

.tasks-context-run-id,
.tasks-context-kpis span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 7px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.tasks-context-run-id {
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  background: rgba(255, 252, 245, 0.28);
}

.tasks-context-run-id code {
  font-family: "Cascadia Code", Consolas, monospace;
}

.tasks-context-progress {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.tasks-context-progress span {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.tasks-context-progress b {
  color: var(--tasks-text);
  font-size: 15px;
  font-weight: 900;
}

.tasks-context-progress i {
  display: block;
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(84, 168, 107, 0.16);
}

.tasks-context-progress em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #54a86b, #9ccb78);
}

.tasks-context-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
  min-width: 0;
}

.tasks-context-kpis .wide {
  grid-column: 1 / -1;
}

.tasks-context-empty,
.task-warning,
.task-empty {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--tasks-muted);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.task-warning,
.task-empty {
  padding: 10px;
  border: 1px dashed var(--tasks-border);
  border-radius: 0;
  background: rgba(255, 242, 210, 0.38);
}

.task-warning {
  color: var(--tasks-danger);
}

.tasks-context-scroll :deep(.task-artifact-panel) {
  --task-panel-bg: transparent;
  --task-panel-soft: rgba(255, 252, 245, 0.28);
  --task-panel-line: rgba(93, 48, 17, 0.14);
  --task-panel-text: var(--tasks-text);
  --task-panel-muted: var(--tasks-muted);
  --task-panel-accent: var(--tasks-accent);
  --task-panel-danger: var(--tasks-danger);
  padding: 11px 12px 12px;
}

.tasks-context-scroll :deep(.task-artifact-panel header) {
  padding-bottom: 7px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
}

.tasks-context-scroll :deep(.task-artifact-panel header b) {
  color: #3b1c09;
  font-size: 13px;
  font-weight: 950;
}

.tasks-context-scroll :deep(.task-artifact-kpis span),
.tasks-context-scroll :deep(.task-artifact-row) {
  border-radius: 0;
  background: rgba(255, 252, 245, 0.28);
}

@media (max-width: 1120px) {
  .tasks-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    margin: 0 12px 10px;
  }

  .tasks-command-metrics,
  .tasks-command-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .tasks-shell,
  .tasks-shell.parchment-logbook {
    grid-template-columns: 220px minmax(0, 1fr) 260px;
    column-gap: 14px;
  }

  .task-row {
    grid-template-columns: 10px minmax(0, 1fr);
  }
}

@media (max-width: 960px) {
  .tasks-page {
    right: 18px;
    left: 18px;
    padding: 0 0 18px;
  }

  .tasks-shell,
  .tasks-shell.parchment-logbook {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto minmax(0, 1fr) auto;
    grid-template-areas:
      "command"
      "rail"
      "pane"
      "context";
    gap: 8px;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 16px;
  }

  .tasks-command-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 10px;
    margin: 0 12px 8px;
    padding: 14px;
  }

  .tasks-command-actions {
    grid-column: auto;
  }

  .tasks-control-rail {
    grid-template-rows: auto auto auto;
    gap: 8px;
    padding: 0 0 8px;
    border-right: none;
    border-bottom: 1px solid var(--tasks-border);
  }

  .task-filter-list {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    overflow-y: hidden;
    padding-right: 0;
    scrollbar-width: none;
  }

  .task-filter-list::-webkit-scrollbar {
    display: none;
  }

  .task-filter-chip {
    flex: 0 0 176px;
  }

  .tasks-main-pane {
    max-height: none;
    overflow: visible;
  }

  .tasks-scroll {
    max-height: none;
    overflow: visible;
    padding: 12px;
  }

  .task-events-content {
    max-height: none;
    overflow: visible;
    padding-right: 0;
  }

  .tasks-context-rail {
    padding: 8px 0 0;
    border-left: none;
    border-top: 1px solid var(--tasks-border);
  }

  .tasks-context-scroll {
    max-height: 420px;
    overflow-y: auto;
  }
}

@media (max-width: 640px) {
  .tasks-page {
    right: 10px;
    left: 10px;
    padding-bottom: 10px;
  }

  .tasks-shell,
  .tasks-shell.parchment-logbook {
    gap: 10px;
    padding: 10px;
  }

  .tasks-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "title action"
      "metrics metrics";
    gap: 6px;
    margin: 0 10px 8px;
    padding: 9px;
  }

  .tasks-command-title {
    grid-area: title;
  }

  .tasks-command-actions {
    grid-area: action;
    align-self: center;
    justify-content: end;
  }

  .tasks-command-metrics {
    grid-area: metrics;
    gap: 12px;
    justify-content: flex-start;
  }

  .tasks-command-title h2 {
    font-size: 18px;
  }

  .tasks-command-metrics small {
    overflow: hidden;
    font-size: 10px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tasks-command-metrics b {
    font-size: 12px;
  }

  .tasks-refresh-button {
    width: auto;
    min-width: 64px;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
  }

  .task-filter-chip {
    flex-basis: 152px;
  }

  .tasks-scroll {
    padding: 10px;
  }

  .tasks-context-kpis {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (min-width: 961px) {
  .tasks-shell,
  .tasks-shell.parchment-logbook {
    grid-template-columns: 252px minmax(0, 1fr) 300px;
    column-gap: 8px;
    padding: 12px;
  }

  .tasks-control-rail {
    gap: 10px;
    padding-right: 14px;
    border-right-color: rgba(93, 48, 17, 0.22);
  }

  .tasks-rail-header {
    min-height: 57px;
    padding: 10px 0 12px;
    border-bottom-color: rgba(93, 48, 17, 0.2);
  }

  .tasks-rail-header span {
    font-size: 22px;
    font-weight: 950;
  }

  .tasks-rail-header strong {
    height: auto;
    padding: 0;
    border-radius: 0;
    background: transparent;
    color: var(--tasks-muted);
    font-size: 13px;
  }

  .task-filter-chip {
    height: 36px;
    padding: 0 11px;
  }

  .tasks-command-bar {
    grid-template-columns: 188px minmax(0, 1fr) 78px;
    gap: 20px;
    min-height: 57px;
    padding: 10px 0 12px;
    border: 0;
    border-bottom: 1px solid rgba(93, 48, 17, 0.2);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .tasks-command-title h2 {
    color: var(--tasks-text);
    font-size: 22px;
    font-weight: 950;
  }

  .tasks-command-metrics {
    gap: 8px;
    justify-content: flex-end;
    width: 100%;
  }

  .tasks-command-metrics span {
    flex: 0 0 78px;
    max-width: 78px;
  }

  .tasks-command-metrics span:nth-child(1) {
    flex-basis: 84px;
    max-width: 84px;
  }

  .tasks-command-metrics span:nth-child(4) {
    flex: 0 0 106px;
    max-width: 106px;
  }

  .tasks-command-metrics small {
    color: var(--tasks-muted);
    font-size: 11px;
  }

  .tasks-command-metrics b {
    color: var(--tasks-text);
    font-size: 13px;
  }

  .tasks-refresh-button {
    min-width: 78px;
    height: 34px;
    padding: 0 12px;
    font-size: 12px;
  }

  .tasks-main-pane {
    align-self: stretch;
    height: 100%;
    max-height: none;
    border: 0;
    border-radius: 0;
    background: transparent;
  }

  .tasks-scroll {
    height: 100%;
    max-height: none;
    padding: 14px 0 12px;
  }
}
</style>
