import type { TaskActionResponse, TaskArtifact, TaskArtifactsResponse, TaskEventsResponse, TaskListResponse, TaskQueueRow } from '../../types/task'
import { arrayOrEmpty, booleanValue, firstNumber, firstString, integerValue, normalizePagination, nullableNumber, objectOrEmpty, shortId, stringValue } from '../common'

const TASK_ACTIVE_STATUSES = new Set(['queued', 'running'])
const TASK_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])

const TASK_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断'
}

function percentValue(value: unknown): number | null {
  const number = nullableNumber(value)
  if (number == null) return null
  const percent = number <= 1 ? number * 100 : number
  return Math.max(0, Math.min(100, Math.round(percent)))
}

function taskProgressPercent(progress: Record<string, unknown>, source: Record<string, unknown>): number {
  const explicit = percentValue(progress.percent ?? progress.overall_percent ?? source.progress_percent)
  if (explicit != null) return explicit
  const completed = firstNumber(progress.completed, progress.completed_games, progress.done, source.completed)
  const total = firstNumber(progress.total, progress.target, progress.target_games, source.total)
  if (completed != null && total != null && total > 0) {
    return Math.max(0, Math.min(100, Math.round((completed / total) * 100)))
  }
  return 0
}

function taskProgressLabel(progress: Record<string, unknown>, percent: number): string {
  const completed = firstNumber(progress.completed, progress.completed_games, progress.done)
  const total = firstNumber(progress.total, progress.target, progress.target_games)
  if (completed != null && total != null && total > 0) return `${completed} / ${total}`
  return percent ? `${percent}%` : '等待'
}

function sizeLabel(bytes: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return '大小未知'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`
}

export function taskStatusLabel(status: unknown): string {
  const key = stringValue(status).toLowerCase()
  return TASK_STATUS_LABELS[key] || stringValue(status, '未知')
}

export function normalizeTask(raw: unknown): TaskQueueRow {
  const source = objectOrEmpty(raw)
  const progress = objectOrEmpty(source.progress)
  const status = stringValue(source.status)
  const percent = taskProgressPercent(progress, source)
  return {
    ...source,
    task_id: firstString(source.task_id, source.id),
    id: firstString(source.task_id, source.id),
    kind: stringValue(source.kind),
    status,
    priority: integerValue(source.priority, 100),
    payload: objectOrEmpty(source.payload),
    result: source.result == null ? null : objectOrEmpty(source.result),
    error: source.error == null ? null : objectOrEmpty(source.error),
    progress: Object.keys(progress).length ? progress : null,
    attempt: integerValue(source.attempt, 0),
    max_attempts: integerValue(source.max_attempts, 1),
    queued_at: stringValue(source.queued_at),
    started_at: stringValue(source.started_at),
    updated_at: stringValue(source.updated_at),
    finished_at: stringValue(source.finished_at),
    cancel_requested: booleanValue(source.cancel_requested, false),
    parent_task_id: stringValue(source.parent_task_id),
    source: stringValue(source.source),
    metadata: objectOrEmpty(source.metadata),
    progressPercent: percent,
    progressLabel: taskProgressLabel(progress, percent),
    stageLabel: firstString(progress.stage, progress.current_stage, source.current_stage, source.stage, status),
    statusLabel: taskStatusLabel(status),
    isActive: TASK_ACTIVE_STATUSES.has(status),
    isTerminal: TASK_TERMINAL_STATUSES.has(status)
  }
}

export function normalizeTaskListResponse(raw: unknown): TaskListResponse {
  const source = objectOrEmpty(raw)
  const rows = (Array.isArray(raw) ? raw : arrayOrEmpty(source.tasks).length ? arrayOrEmpty(source.tasks) : arrayOrEmpty(source.items)).map(normalizeTask)
  return {
    tasks: rows,
    pagination: source.pagination ? normalizePagination(source.pagination, rows) : undefined,
    raw
  }
}

export function normalizeTaskResponse(raw: unknown): TaskQueueRow {
  const source = objectOrEmpty(raw)
  return normalizeTask(source.task ?? source.data ?? raw)
}

export function normalizeTaskArtifact(raw: unknown): TaskArtifact {
  const source = objectOrEmpty(raw)
  const name = firstString(source.name, source.relative_path, source.artifact_id)
  const contentType = stringValue(source.content_type).toLowerCase()
  const size = nullableNumber(source.size_bytes)
  const artifactType = stringValue(source.artifact_type)
  const sha = stringValue(source.sha256)
  return {
    ...source,
    artifact_id: firstString(source.artifact_id, source.id),
    id: firstString(source.artifact_id, source.id),
    task_id: stringValue(source.task_id),
    artifact_type: artifactType,
    name,
    relative_path: stringValue(source.relative_path),
    content_type: contentType,
    size_bytes: size,
    sha256: sha,
    created_at: stringValue(source.created_at),
    metadata: objectOrEmpty(source.metadata),
    isJson: contentType.includes('json') || /\.json$/i.test(name),
    sizeLabel: sizeLabel(size),
    shortSha: sha ? shortId(sha.replace(/^sha256:/, ''), 12) : ''
  }
}

export function normalizeTaskArtifactsResponse(raw: unknown): TaskArtifactsResponse {
  const source = objectOrEmpty(raw)
  return {
    task_id: stringValue(source.task_id),
    artifacts: arrayOrEmpty(source.artifacts ?? source.items).map(normalizeTaskArtifact),
    raw
  }
}

export function normalizeTaskEventsResponse(raw: unknown): TaskEventsResponse {
  const source = objectOrEmpty(raw)
  return {
    task_id: stringValue(source.task_id),
    after_event_id: integerValue(source.after_event_id, 0),
    events: arrayOrEmpty(source.events ?? source.items).map((item) => {
      const event = objectOrEmpty(item)
      const eventType = firstString(event.event_type, event.event, event.type)
      return {
        ...event,
        event_type: eventType,
        type: eventType
      }
    }),
    raw
  }
}

export function normalizeTaskActionResponse(raw: unknown): TaskActionResponse {
  const source = objectOrEmpty(raw)
  return {
    task_id: stringValue(source.task_id),
    action: stringValue(source.action),
    changed: booleanValue(source.changed, false),
    task: normalizeTask(source.task),
    raw
  }
}
