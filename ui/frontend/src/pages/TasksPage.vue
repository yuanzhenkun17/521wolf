<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LabWorkbenchShell from '../components/lab/LabWorkbenchShell.vue'
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

function selectFilter(filter: StatusFilterKey) {
  activeFilter.value = filter
}

function selectTask(task: TaskQueueRow | null) {
  const nextId = task?.task_id || task?.id || ''
  selectedTaskId.value = nextId
  selectedTask.value = task
  events.value = []
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
    <LabWorkbenchShell
      workbench-key="tasks"
      title="任务中心"
      eyebrow="Task Queue"
      :tabs="[]"
      :meta="taskMetaRows"
      action-label="刷新"
      action-busy-label="刷新中"
      :action-busy="loading"
      :action-disabled="loading"
      rail-label="任务筛选"
      context-label="任务详情"
      main-label="任务列表与事件"
      @action="refreshAll"
    >
      <template #rail>
        <aside class="tasks-rail">
          <header>
            <small>状态筛选</small>
            <b>{{ visibleTasks.length }} / {{ tasks.length }}</b>
          </header>
          <div class="task-filter-list">
            <button
              v-for="filter in STATUS_FILTERS"
              :key="filter.key"
              type="button"
              :class="{ active: activeFilter === filter.key }"
              @click="selectFilter(filter.key)"
            >
              <span>
                <b>{{ filter.label }}</b>
                <small>{{ filter.caption }}</small>
              </span>
              <em>{{ statusCountFor(filter) }}</em>
            </button>
          </div>
          <label class="task-search">
            <span>搜索</span>
            <input v-model="searchText" type="search" placeholder="task / kind / stage" />
          </label>
          <p v-if="refreshedAt" class="task-refresh-note">最后刷新 {{ formatDateTime(refreshedAt) }}</p>
        </aside>
      </template>

      <template #context>
        <section class="tasks-context">
          <article class="task-detail-panel">
            <header>
              <div>
                <small>当前任务</small>
                <h2 :title="activeTask?.task_id || ''">{{ shortTaskId(activeTask?.task_id) }}</h2>
              </div>
              <b v-if="activeTask">{{ activeTask.statusLabel }}</b>
            </header>
            <div v-if="detailLoading" class="task-empty">正在读取任务详情。</div>
            <div v-else-if="detailError" class="task-warning">{{ detailError }}</div>
            <div v-else-if="activeTask" class="task-detail-grid">
              <span v-for="item in contextRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
            <div v-else class="task-empty">未选择任务。</div>
          </article>

          <TaskArtifactPanel
            v-if="selectedTaskId"
            :task-id="selectedTaskId"
            title="任务产物与控制"
            eyebrow="ArtifactStore"
            show-actions
            @action-complete="handleTaskAction"
          />
        </section>
      </template>

      <section class="tasks-main">
        <div v-if="error" class="task-warning">{{ error }}</div>
        <div class="task-table" aria-label="任务列表">
          <button
            v-for="task in visibleTasks"
            :key="task.task_id"
            type="button"
            :class="['task-row', { selected: selectedTaskId === task.task_id }]"
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
              <i aria-hidden="true"><em :style="{ width: `${task.progressPercent}%` }"></em></i>
            </span>
            <span class="task-time-cell">
              <b>{{ task.progressLabel }}</b>
              <small>{{ formatDateTime(task.updated_at || task.queued_at) || '未记录' }}</small>
            </span>
          </button>
          <div v-if="!visibleTasks.length && !loading" class="task-empty">当前筛选无任务。</div>
          <div v-if="loading" class="task-empty">正在读取任务队列。</div>
        </div>

        <section class="task-events-panel" aria-label="任务事件时间线">
          <header>
            <div>
              <small>事件时间线</small>
              <h2>{{ eventRows.length }} 条事件</h2>
            </div>
            <button type="button" :disabled="!selectedTaskId || eventsLoading" @click="loadSelectedTask">
              {{ eventsLoading ? '读取中' : '刷新事件' }}
            </button>
          </header>
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
        </section>
      </section>
    </LabWorkbenchShell>
  </section>
</template>

<style scoped>
.tasks-page {
  --tasks-bg: var(--logbook-bg, #f2dfae);
  --tasks-panel: var(--logbook-panel, rgba(255, 252, 245, 0.82));
  --tasks-panel-soft: var(--logbook-panel-soft, rgba(255, 250, 240, 0.58));
  --tasks-border: var(--logbook-border, rgba(93, 48, 17, 0.18));
  --tasks-border-strong: var(--logbook-border-strong, rgba(93, 48, 17, 0.34));
  --tasks-text: var(--logbook-text, #3a2a18);
  --tasks-muted: var(--logbook-muted, rgba(93, 48, 17, 0.66));
  --tasks-accent: var(--logbook-accent-strong, #5a3319);
  --tasks-danger: var(--logbook-danger, #993026);
  --lab-rail-width: 276px;
  --lab-context-width: 360px;
  height: 100%;
  min-height: 0;
  background: transparent;
  color: var(--tasks-text);
}

.tasks-page :deep(.lab-workbench-shell--tasks) {
  --lab-bg: var(--tasks-bg);
  --lab-panel: var(--tasks-panel);
  --lab-border: var(--tasks-border);
  --lab-border-strong: var(--tasks-border-strong);
  --lab-text: var(--tasks-text);
  --lab-muted: var(--tasks-muted);
  --lab-accent: var(--tasks-accent);
  --lab-danger: var(--tasks-danger);
}

.tasks-rail,
.tasks-context,
.tasks-main,
.task-detail-panel,
.task-events-panel {
  min-width: 0;
  min-height: 0;
}

.tasks-rail,
.tasks-context {
  display: grid;
  gap: 10px;
  align-content: start;
}

.tasks-rail {
  height: 100%;
  padding: 12px;
  border: 1px solid var(--tasks-border);
  border-radius: 8px;
  background: var(--tasks-panel);
  overflow: auto;
}

.tasks-rail header,
.task-detail-panel header,
.task-events-panel header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.tasks-rail small,
.task-detail-panel small,
.task-events-panel small,
.task-row small,
.task-search span,
.task-refresh-note {
  color: var(--tasks-muted);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0;
}

.tasks-rail b,
.task-detail-panel b,
.task-events-panel b,
.task-row b {
  min-width: 0;
  overflow: hidden;
  color: var(--tasks-text);
  font-size: 12px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-filter-list {
  display: grid;
  gap: 7px;
}

.task-filter-list button,
.task-row,
.task-events-panel button {
  border: 1px solid var(--tasks-border);
  border-radius: 7px;
  background: var(--tasks-panel-soft);
  color: var(--tasks-text);
  cursor: pointer;
}

.task-filter-list button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 9px;
  text-align: left;
}

.task-filter-list button span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.task-filter-list button em {
  display: inline-flex;
  min-width: 28px;
  min-height: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.1);
  color: var(--tasks-accent);
  font-size: 11px;
  font-style: normal;
  font-weight: 950;
}

.task-filter-list button.active,
.task-row.selected {
  border-color: color-mix(in srgb, var(--tasks-accent) 42%, transparent);
  background: color-mix(in srgb, var(--tasks-accent) 10%, var(--tasks-panel-soft));
}

.task-search {
  display: grid;
  gap: 5px;
}

.task-search input {
  width: 100%;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--tasks-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.64);
  color: var(--tasks-text);
  font-size: 12px;
  font-weight: 800;
  outline: none;
}

.task-refresh-note {
  margin: 0;
}

.tasks-main {
  display: grid;
  grid-template-rows: minmax(190px, 0.9fr) minmax(220px, 1.1fr);
  gap: 10px;
  height: 100%;
  overflow: hidden;
}

.task-table,
.task-events-panel,
.task-detail-panel {
  border: 1px solid var(--tasks-border);
  border-radius: 8px;
  background: var(--tasks-panel);
}

.task-table {
  display: grid;
  align-content: start;
  gap: 6px;
  min-height: 0;
  padding: 10px;
  overflow: auto;
}

.task-row {
  display: grid;
  grid-template-columns: 10px minmax(0, 1.3fr) minmax(118px, 0.8fr) minmax(128px, 0.75fr);
  gap: 10px;
  align-items: center;
  width: 100%;
  min-height: 54px;
  padding: 8px 10px;
  text-align: left;
}

.task-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--tasks-muted);
}

.task-row[data-status="queued"] .task-status-dot,
.task-row[data-status="running"] .task-status-dot {
  background: #7b8d42;
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

.task-events-panel,
.task-detail-panel {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  padding: 12px;
  overflow: auto;
}

.task-events-panel header h2,
.task-detail-panel header h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--tasks-text);
  font-size: 16px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-events-panel button {
  min-height: 30px;
  padding: 0 10px;
  color: var(--tasks-accent);
  font-size: 11px;
  font-weight: 900;
}

.task-events-panel button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.task-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.task-detail-grid span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--tasks-border);
  border-radius: 7px;
  background: var(--tasks-panel-soft);
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
  border: 1px solid var(--tasks-border);
  border-radius: 7px;
  background: var(--tasks-panel-soft);
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
  background: rgba(45, 34, 24, 0.94);
  color: #f6e6c8;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.task-warning,
.task-empty {
  margin: 0;
  padding: 10px;
  border: 1px dashed var(--tasks-border);
  border-radius: 7px;
  background: var(--tasks-panel-soft);
  color: var(--tasks-muted);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.task-warning {
  color: var(--tasks-danger);
}

@media (max-width: 1120px) {
  .tasks-main {
    grid-template-rows: auto auto;
    overflow: auto;
  }

  .task-row {
    grid-template-columns: 10px minmax(0, 1fr);
  }
}
</style>
