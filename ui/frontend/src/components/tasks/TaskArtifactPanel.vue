<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { createTaskService } from '../../services/taskApi'
import type { TaskActionResponse, TaskArtifact, TaskQueueRow } from '../../types/task'

const props = withDefaults(defineProps<{
  taskId?: string
  title?: string
  eyebrow?: string
  compact?: boolean
  showActions?: boolean
}>(), {
  taskId: '',
  title: '任务状态',
  eyebrow: 'Task Queue',
  compact: false,
  showActions: false
})
const emit = defineEmits<{
  'action-complete': [response: TaskActionResponse]
}>()

const taskService = createTaskService()
const task = ref<TaskQueueRow | null>(null)
const artifacts = ref<TaskArtifact[]>([])
const loading = ref(false)
const actionLoading = ref('')
const error = ref('')
const previewArtifactId = ref('')
const previewText = ref('')
const previewError = ref('')
let requestSeq = 0

const normalizedTaskId = computed(() => String(props.taskId || '').trim())
const hasTaskId = computed(() => Boolean(normalizedTaskId.value))
const canCancel = computed(() => Boolean(task.value?.isActive) && !task.value?.cancel_requested)
const canRetry = computed(() => ['failed', 'interrupted'].includes(String(task.value?.status || '')))
const statusTone = computed(() => {
  const status = String(task.value?.status || '').toLowerCase()
  if (status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'interrupted') return 'danger'
  if (status === 'cancelled') return 'muted'
  if (status === 'queued' || status === 'running') return 'active'
  return 'neutral'
})
const progressWidth = computed(() => `${Math.max(0, Math.min(100, task.value?.progressPercent || 0))}%`)
const taskErrorText = computed(() => {
  const source = task.value?.error || {}
  return firstText(source.message, source.detail, source.error, error.value)
})
const visibleArtifacts = computed(() => artifacts.value.slice(0, props.compact ? 4 : 8))
const hiddenArtifactCount = computed(() => Math.max(0, artifacts.value.length - visibleArtifacts.value.length))

watch(
  normalizedTaskId,
  () => {
    void refresh()
  },
  { immediate: true }
)

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value != null && typeof value !== 'object') {
      const text = String(value).trim()
      if (text) return text
    }
  }
  return ''
}

function errorMessage(err: unknown, fallback: string): string {
  const source = err as { status?: number; message?: string }
  if (source?.status === 404) return '未找到队列任务'
  return firstText(source?.message, fallback)
}

async function refresh() {
  const taskId = normalizedTaskId.value
  requestSeq += 1
  const seq = requestSeq
  task.value = null
  artifacts.value = []
  previewArtifactId.value = ''
  previewText.value = ''
  previewError.value = ''
  error.value = ''
  if (!taskId) return
  loading.value = true
  try {
    const [taskResult, artifactResult] = await Promise.allSettled([
      taskService.get(taskId),
      taskService.artifacts(taskId)
    ])
    if (seq !== requestSeq) return
    if (taskResult.status === 'fulfilled') {
      task.value = taskResult.value
    } else {
      error.value = errorMessage(taskResult.reason, '任务状态读取失败')
    }
    if (artifactResult.status === 'fulfilled') {
      artifacts.value = artifactResult.value.artifacts
    } else if (!error.value) {
      error.value = errorMessage(artifactResult.reason, '任务产物读取失败')
    }
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function runAction(action: 'cancel' | 'retry') {
  const taskId = normalizedTaskId.value
  if (!taskId || actionLoading.value) return
  actionLoading.value = action
  error.value = ''
  try {
    const result = action === 'cancel'
      ? await taskService.cancel(taskId)
      : await taskService.retry(taskId)
    task.value = result.task
    await refresh()
    emit('action-complete', result)
  } catch (err) {
    error.value = errorMessage(err, action === 'cancel' ? '取消任务失败' : '重试任务失败')
  } finally {
    actionLoading.value = ''
  }
}

async function previewJson(artifact: TaskArtifact) {
  if (!artifact.isJson) return
  const taskId = normalizedTaskId.value
  previewArtifactId.value = artifact.artifact_id
  previewText.value = ''
  previewError.value = ''
  try {
    const payload = await taskService.previewJsonArtifact(taskId, artifact.artifact_id)
    previewText.value = JSON.stringify(payload, null, 2)
  } catch (err) {
    previewError.value = errorMessage(err, 'JSON 预览读取失败')
  }
}

function artifactHref(artifact: TaskArtifact): string {
  const taskId = normalizedTaskId.value
  return taskId && artifact.artifact_id ? taskService.artifactUrl(taskId, artifact.artifact_id) : '#'
}

function artifactMeta(artifact: TaskArtifact): string {
  return [
    artifact.artifact_type || 'artifact',
    artifact.sizeLabel,
    artifact.shortSha ? `sha ${artifact.shortSha}` : ''
  ].filter(Boolean).join(' / ')
}
</script>

<template>
  <section
    :class="['task-artifact-panel', { compact, empty: !hasTaskId }]"
    :data-status="task?.status || ''"
    aria-label="任务状态与产物"
  >
    <header>
      <span>
        <small>{{ eyebrow }}</small>
        <b>{{ title }}</b>
      </span>
      <button type="button" :disabled="loading || !hasTaskId" @click="refresh">
        {{ loading ? '读取中' : '刷新' }}
      </button>
    </header>

    <div v-if="!hasTaskId" class="task-artifact-empty">未选择任务</div>
    <template v-else>
      <div v-if="task" class="task-artifact-status">
        <span :class="['task-status-pill', `tone-${statusTone}`]">{{ task.statusLabel }}</span>
        <span>{{ task.kind || 'task' }}</span>
        <span>{{ task.cancel_requested ? '取消请求已提交' : task.stageLabel }}</span>
      </div>

      <div v-if="task" class="task-artifact-progress">
        <i :style="{ width: progressWidth }"></i>
      </div>

      <div v-if="task" class="task-artifact-kpis">
        <span>
          <small>进度</small>
          <b>{{ task.progressLabel }}</b>
        </span>
        <span>
          <small>尝试</small>
          <b>{{ task.attempt }} / {{ task.max_attempts }}</b>
        </span>
        <span>
          <small>产物</small>
          <b>{{ artifacts.length }}</b>
        </span>
      </div>

      <p v-if="taskErrorText" class="task-artifact-error">{{ taskErrorText }}</p>
      <p v-else-if="error" class="task-artifact-error">{{ error }}</p>

      <div v-if="task && showActions" class="task-artifact-actions">
        <button type="button" :disabled="!canCancel || Boolean(actionLoading)" @click="runAction('cancel')">
          {{ actionLoading === 'cancel' ? '取消中' : '取消' }}
        </button>
        <button type="button" :disabled="!canRetry || Boolean(actionLoading)" @click="runAction('retry')">
          {{ actionLoading === 'retry' ? '重试中' : '重试' }}
        </button>
      </div>

      <div v-if="visibleArtifacts.length" class="task-artifact-list">
        <article v-for="artifact in visibleArtifacts" :key="artifact.artifact_id" class="task-artifact-row">
          <span>
            <b :title="artifact.name">{{ artifact.name }}</b>
            <small :title="artifactMeta(artifact)">{{ artifactMeta(artifact) }}</small>
          </span>
          <div>
            <button v-if="artifact.isJson" type="button" @click="previewJson(artifact)">预览</button>
            <a :href="artifactHref(artifact)" :download="artifact.name">下载</a>
          </div>
        </article>
        <p v-if="hiddenArtifactCount" class="task-artifact-more">还有 {{ hiddenArtifactCount }} 个产物</p>
      </div>
      <div v-else-if="task && !loading && !error" class="task-artifact-empty">暂无产物</div>

      <div v-if="previewArtifactId" class="task-artifact-preview">
        <div>
          <small>JSON 预览</small>
          <button type="button" @click="previewArtifactId = ''; previewText = ''; previewError = ''">关闭</button>
        </div>
        <p v-if="previewError" class="task-artifact-error">{{ previewError }}</p>
        <pre v-else>{{ previewText || '读取中' }}</pre>
      </div>
    </template>
  </section>
</template>

<style scoped>
.task-artifact-panel {
  --task-panel-bg: var(--report-panel, var(--evo-card-bg, var(--bench-panel, rgba(255, 252, 245, 0.78))));
  --task-panel-soft: var(--report-soft, var(--bench-panel-soft, rgba(255, 250, 240, 0.62)));
  --task-panel-line: var(--report-line, var(--evo-border, var(--bench-border, rgba(139, 94, 52, 0.16))));
  --task-panel-text: var(--report-ink, var(--evo-text, var(--bench-text, #3a2a18)));
  --task-panel-muted: var(--report-muted, var(--evo-text-secondary, var(--bench-text-secondary, #8b6b4a)));
  --task-panel-accent: var(--report-accent, var(--evo-accent, var(--bench-accent, #8b5e34)));
  --task-panel-danger: var(--report-danger, var(--evo-danger, var(--bench-danger, #993026)));
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--task-panel-line);
  border-radius: 8px;
  background: var(--task-panel-bg);
  color: var(--task-panel-text);
}

.task-artifact-panel header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.task-artifact-panel header span,
.task-artifact-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.task-artifact-panel small {
  color: var(--task-panel-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.task-artifact-panel b {
  min-width: 0;
  overflow: hidden;
  color: var(--task-panel-text);
  font-size: 12px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-artifact-panel header b {
  font-size: 13px;
}

.task-artifact-panel button,
.task-artifact-row a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--task-panel-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.66);
  color: var(--task-panel-accent);
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
  cursor: pointer;
}

.task-artifact-panel button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.task-artifact-status {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.task-artifact-status span {
  max-width: 100%;
  overflow: hidden;
  padding: 4px 7px;
  border: 1px solid var(--task-panel-line);
  border-radius: 999px;
  background: var(--task-panel-soft);
  color: var(--task-panel-muted);
  font-size: 11px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-artifact-status .task-status-pill {
  color: var(--task-panel-text);
}

.task-status-pill.tone-success {
  border-color: rgba(106, 95, 35, 0.28);
  background: rgba(211, 190, 112, 0.18);
}

.task-status-pill.tone-danger {
  border-color: rgba(153, 48, 38, 0.3);
  background: rgba(153, 48, 38, 0.07);
  color: var(--task-panel-danger);
}

.task-status-pill.tone-active {
  border-color: rgba(139, 94, 52, 0.28);
  background: rgba(139, 94, 52, 0.1);
}

.task-artifact-progress {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.12);
}

.task-artifact-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--task-panel-accent);
  transition: width 0.2s ease;
}

.task-artifact-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.task-artifact-kpis span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid var(--task-panel-line);
  border-radius: 7px;
  background: var(--task-panel-soft);
}

.task-artifact-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.task-artifact-list {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.task-artifact-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--task-panel-line);
  border-radius: 7px;
  background: var(--task-panel-soft);
}

.task-artifact-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-transform: none;
}

.task-artifact-row div {
  display: flex;
  gap: 5px;
}

.task-artifact-error,
.task-artifact-empty,
.task-artifact-more {
  margin: 0;
  color: var(--task-panel-muted);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.42;
}

.task-artifact-error {
  color: var(--task-panel-danger);
  overflow-wrap: anywhere;
}

.task-artifact-empty {
  padding: 10px;
  border: 1px dashed var(--task-panel-line);
  border-radius: 7px;
  background: var(--task-panel-soft);
}

.task-artifact-preview {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.task-artifact-preview > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.task-artifact-preview pre {
  max-height: 260px;
  min-width: 0;
  overflow: auto;
  margin: 0;
  padding: 9px;
  border: 1px solid var(--task-panel-line);
  border-radius: 7px;
  background: rgba(45, 34, 24, 0.94);
  color: #f6e6c8;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.task-artifact-panel.compact {
  gap: 8px;
  padding: 10px;
}

@media (max-width: 640px) {
  .task-artifact-kpis,
  .task-artifact-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .task-artifact-actions,
  .task-artifact-row div {
    justify-content: flex-start;
  }
}
</style>
